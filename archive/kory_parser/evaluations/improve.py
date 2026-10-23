"""Bounded Codex repair loop. Accepted candidates remain reviewable; no source auto-apply."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .execution import run_process
from .runner import (
    PROJECT,
    compare_reports,
    evaluate,
    input_bytes,
    load_manifest,
    sha,
    tree_digest,
    write_json,
)

SKILL = PROJECT.parents[1] / ".agents/skills/improve_kory_parser/SKILL.md"


def snapshot(source, destination):
    destination.mkdir(parents=True)
    for name in ("src", "tests", "evaluations", "docs", "third_party"):
        shutil.copytree(
            source / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
    for name in ("pyproject.toml", "uv.lock", "LICENSE", "NOTICE"):
        shutil.copy2(source / name, destination / name)


def protected_files(candidate):
    """Only parser source edits and NEW regression tests are accepted."""
    return {
        p.relative_to(candidate).as_posix(): sha(p.read_bytes())
        for p in candidate.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and not p.relative_to(candidate).as_posix().startswith(("src/", ".pytest_cache/", ".ruff_cache/"))
    }


def integrity(candidate, protected):
    for name, digest in protected.items():
        path = candidate / name
        if not path.is_file() or path.is_symlink() or sha(path.read_bytes()) != digest:
            return False
    for path in candidate.rglob("*"):
        if path.is_symlink():
            return False
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        name = path.relative_to(candidate).as_posix()
        if name not in protected and not name.startswith(
            ("src/", "tests/", ".pytest_cache/", ".ruff_cache/", ".artifacts/")
        ):
            return False
    return True


def codex_command(executable, candidate, model):
    command = [
        executable,
        "exec",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--cd",
        str(candidate),
        "--json",
    ]
    if model:
        command += ["--model", model]
    return command + ["-"]


def improve(
    manifest,
    output,
    *,
    iterations=3,
    seconds=900,
    patience=2,
    executor="codex",
    model=None,
    corpus_root=None,
    dry_run=False,
    skill_path=None,
):
    if iterations < 1 or patience < 1 or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Budgets must be positive and finite")
    data = load_manifest(manifest)
    skill_path = skill_path or SKILL
    if {case["split"] for case in data["cases"]} != {"development", "validation"}:
        raise ValueError("Improvement requires both development and validation cases")
    output = output.resolve()
    if output == PROJECT or PROJECT.is_relative_to(output):
        raise ValueError("Output cannot contain the source project")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + seconds
    summary = {
        "schema_version": 1,
        "manifest_sha256": sha(manifest.read_bytes()),
        "iterations_budget": iterations,
        "seconds_budget": seconds,
        "patience": patience,
        "model": model or "Codex configured default",
        "executor": executor,
        "attempts": [],
        "accepted_candidate": None,
        "stop_reason": None,
        "automatic_apply": False,
    }
    # Pin inputs outside the agent's writable candidate directory.
    pinned = output / "manifest.json"
    shutil.copyfile(manifest, pinned)
    root = (corpus_root or manifest.resolve().parent).resolve()
    try:
        baseline = evaluate(
            pinned, output / "baseline", candidate=PROJECT, corpus_root=root, deadline=deadline
        )
        if dry_run or baseline["passed"]:
            summary["stop_reason"] = "dry_run" if dry_run else "all_checks_passed"
            return summary
        if shutil.which(executor) is None:
            raise ValueError("Codex executable is not available")
        current = PROJECT
        stale = 0
        for index in range(1, iterations + 1):
            if time.monotonic() >= deadline:
                summary["stop_reason"] = "time_budget"
                break
            failures = [
                row for row in baseline["cases"] if row["split"] == "development" and not row["passed"]
            ]
            if not failures:
                summary["stop_reason"] = "validation_requires_review"
                break
            directory = output / f"iteration_{index:03d}"
            candidate = directory / "candidate"
            snapshot(current, candidate)
            # A nested repository keeps Codex's workspace root at this candidate,
            # rather than discovering the enclosing Teoria checkout.
            initialized = run_process(
                ["git", "init", "--quiet", str(candidate)],
                cwd=directory,
                timeout=max(0.001, deadline - time.monotonic()),
            )
            if initialized.returncode:
                raise ValueError("Cannot initialize candidate workspace")
            # Only development evidence is supplied to the repair executor.
            dev = copy.deepcopy(data)
            dev["cases"] = [case for case in dev["cases"] if case["split"] == "development"]
            shutil.rmtree(candidate / "evaluations/corpus")
            (candidate / "evaluations/corpus").mkdir()
            for case in dev["cases"]:
                if "source_path" in case:
                    data_bytes = input_bytes(case, root)
                    case["source_path"] = case["id"] + "." + case["format"]
                    (candidate / "evaluations/corpus" / case["source_path"]).write_bytes(data_bytes)
            write_json(candidate / "evaluations/corpus/development.json", dev)
            skill = skill_path.read_text()
            (candidate / "AGENTS.md").write_text(skill.split("---", 2)[-1])
            protected = protected_files(candidate)
            before_source = tree_digest(candidate / "src")
            prompt = (
                "Improve Kory Parser in this isolated candidate. Follow AGENTS.md. "
                "Fix one reproducible development failure and add a new regression test. "
                "Edit src/ and add tests only; do not alter existing tests or evaluation criteria. "
                "Do not launch another improvement loop, publish, commit or access validation data. "
                "Use the current Python interpreter: " + sys.executable + ". "
                "New tests must use only existing dependencies. "
                "Run Python with PYTHONPATH=src so it imports this candidate; do not install packages. "
                "For local evaluation pass --manifest evaluations/corpus/development.json "
                "and write outputs under .artifacts/. "
                "If no supported fix is possible, explain and stop. Development failures:\n"
                + json.dumps(failures, ensure_ascii=False)
            )
            command = codex_command(executor, candidate, model)
            attempt = {"iteration": index, "accepted": False, "reason": None}
            summary["attempts"].append(attempt)
            run = run_process(command, cwd=candidate, timeout=deadline - time.monotonic(), input=prompt)
            # Executor output may contain source text: keep it local, never echo it.
            (directory / "executor.jsonl").write_text(run.stdout)
            (directory / "executor_stderr.log").write_text(run.stderr)
            if run.returncode or not integrity(candidate, protected):
                attempt["reason"] = "executor_failed" if run.returncode else "protected_files_changed"
                summary["stop_reason"] = attempt["reason"]
                break
            new_tests = [
                p
                for p in (candidate / "tests").rglob("test_*.py")
                if p.relative_to(candidate).as_posix() not in protected
            ]
            if not new_tests or before_source == tree_digest(candidate / "src"):
                attempt["reason"] = "no_repair_with_regression_test"
                stale += 1
                if stale >= patience:
                    summary["stop_reason"] = "no_progress"
                    break
                continue
            env = dict(os.environ, PYTHONPATH=str(candidate / "src"))
            # Frozen original tests plus newly added tests, using the candidate implementation.
            for name, test_root, cwd in (
                ("original_tests", PROJECT / "tests", PROJECT),
                ("candidate_tests", candidate / "tests", candidate),
            ):
                tests = run_process(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-c",
                        str(PROJECT / "pyproject.toml"),
                        str(test_root),
                    ],
                    cwd=cwd,
                    env=env,
                    timeout=max(0.001, deadline - time.monotonic()),
                )
                (directory / f"{name}.log").write_text(tests.stdout + tests.stderr)
                if tests.returncode:
                    attempt["reason"] = "tests_failed"
                    break
            if attempt["reason"]:
                stale += 1
            else:
                regression = run_process(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-c",
                        str(PROJECT / "pyproject.toml"),
                        *[str(path) for path in new_tests],
                    ],
                    cwd=candidate,
                    env=dict(os.environ, PYTHONPATH=str(current / "src")),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
                (directory / "regression_before.log").write_text(regression.stdout + regression.stderr)
                if regression.returncode != 1:
                    attempt["reason"] = "regression_test_did_not_reproduce"
                    stale += 1
                    if stale >= patience:
                        summary["stop_reason"] = "no_progress"
                        break
                    continue
                report = evaluate(
                    pinned, directory / "evaluation", candidate=candidate, corpus_root=root, deadline=deadline
                )
                comparison = compare_reports(baseline, report)
                development_ids = {case["id"] for case in dev["cases"]}
                if not any(item.split(":", 1)[0] in development_ids for item in comparison["improvements"]):
                    comparison["accepted"] = False
                write_json(directory / "comparison.json", comparison)
                attempt.update(comparison)
                attempt["reason"] = "improved" if comparison["accepted"] else "regression_or_no_improvement"
                if comparison["accepted"]:
                    baseline, current, stale = report, candidate, 0
                    summary["accepted_candidate"] = str(candidate)
                else:
                    stale += 1
                if report["passed"] and comparison["accepted"]:
                    summary["stop_reason"] = "all_checks_passed"
                    break
            if stale >= patience:
                summary["stop_reason"] = "no_progress"
                break
        if summary["stop_reason"] is None:
            summary["stop_reason"] = "iteration_budget"
    except (TimeoutError, subprocess.TimeoutExpired):
        summary["stop_reason"] = "time_budget"
    except KeyboardInterrupt:
        summary["stop_reason"] = "interrupted"
    except (OSError, ValueError, KeyError) as error:
        summary["stop_reason"] = "execution_error"
        summary["error_type"] = type(error).__name__
    finally:
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(output / "loop.json", summary)
        lines = [
            "# Kory Parser improvement loop",
            "",
            f"Stop: {summary['stop_reason']}",
            f"Accepted candidate: {summary['accepted_candidate'] or 'none'}",
            "",
            "Candidates remain local for review; source files were not automatically applied.",
        ]
        for attempt in summary["attempts"]:
            lines.append(f"- Iteration {attempt['iteration']}: {attempt['reason']}")
        (output / "loop.md").write_text("\n".join(lines) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT / "evaluations/corpus/seed.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=900)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--executor", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--skill", type=Path, default=SKILL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = improve(
            args.manifest.resolve(),
            args.output,
            iterations=args.iterations,
            seconds=args.seconds,
            patience=args.patience,
            executor=args.executor,
            model=args.model,
            corpus_root=args.corpus_root,
            dry_run=args.dry_run,
            skill_path=args.skill,
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"Loop failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(
        json.dumps({"stop_reason": result["stop_reason"], "accepted_candidate": result["accepted_candidate"]})
    )
    return (
        2
        if result["stop_reason"]
        in {
            "execution_error",
            "executor_failed",
            "protected_files_changed",
            "time_budget",
            "interrupted",
            "validation_requires_review",
        }
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
