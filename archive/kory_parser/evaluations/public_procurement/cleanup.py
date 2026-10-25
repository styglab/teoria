"""Release regenerable cycle artifacts while preserving regression inputs and evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .history import DEFAULT_HISTORY, PROJECT, CorpusHistory, atomic_json

LEGACY_INSTALLS = {"install_native", "install_base", "install_wheel"}


def allocated_bytes(path):
    if path.is_symlink():
        raise ValueError("Refuse to follow cleanup symlinks")
    if path.is_file():
        return path.stat().st_blocks * 512
    total = 0
    for directory, _, files in os.walk(path):
        for name in files:
            total += (Path(directory) / name).lstat().st_blocks * 512
    return total


def protected_sources(state):
    rows = json.loads(Path(state["regression"]["path"]).read_text())
    return {Path(row["source_path"]).resolve() for row in rows}


def active_path(path):
    """Leave a generated environment alone if a running process uses it."""
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            cwd = (process / "cwd").resolve()
            if cwd == path or cwd.is_relative_to(path):
                return True
            if str(path).encode() in (process / "cmdline").read_bytes():
                return True
        except (OSError, RuntimeError):
            continue
    return False


def remove_paths(paths, protected, *, apply):
    report = []
    for path in sorted({Path(p).absolute() for p in paths}):
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError("Refuse cleanup symlink")
        path = path.resolve()
        if any(path == source or source.is_relative_to(path) for source in protected):
            report.append({"path": str(path), "status": "protected_source"})
            continue
        if path.is_dir() and active_path(path):
            report.append({"path": str(path), "status": "active_process"})
            continue
        size = allocated_bytes(path)
        if apply:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        report.append(
            {"path": str(path), "allocated_bytes": size, "status": "removed" if apply else "planned"}
        )
    return report


def legacy_environments(project=PROJECT):
    artifacts = project / ".artifacts"
    result = []
    for directory, dirs, _ in os.walk(artifacts):
        for name in dirs[:]:
            path = Path(directory) / name
            if (
                name in LEGACY_INSTALLS
                or name == ".venv"
                or name == "node_modules"
                and path.parent.name == "ocr_reference_env"
            ):
                result.append(path)
                dirs.remove(name)
    old = project.parents[1] / ".artifacts/procurement_specifications/parser_evaluation_2026_10_20"
    result.extend([old / ".venv", old / "model_cache"])
    return result


def cleanup_cycle(root, *, apply=False, history_path=DEFAULT_HISTORY):
    root = root.resolve()
    if not root.is_relative_to(PROJECT / ".artifacts"):
        raise ValueError("Cycle cleanup is limited to the parser artifact directory")
    acceptance_path = root / "acceptance/acceptance.json"
    summaries = [p for p in root.glob("*/summary.json") if p.is_file()]
    if not acceptance_path.exists() or not summaries:
        return {"status": "not_finished", "removed_bytes": 0, "paths": []}
    acceptance = json.loads(acceptance_path.read_text())
    if acceptance.get("accepted") is not True and acceptance.get("accepted") is not False:
        raise ValueError("Incomplete acceptance decision")
    if acceptance["accepted"] and not acceptance.get("applied"):
        return {"status": "not_finished", "removed_bytes": 0, "paths": []}
    if not Path(history_path).exists():
        return {"status": "missing_history", "removed_bytes": 0, "paths": []}
    with CorpusHistory(history_path) as history:
        history.regression_bytes()
        protected = protected_sources(history.state)
        paths = []
        keep_ids = set(acceptance.get("changed_documents", []))
        labels = root / "source_labels.json"
        if labels.exists():
            keep_ids.update(row["document_id"] for row in json.loads(labels.read_text()).get("cases", []))
        issues = root / "next_issues.json"
        if issues.exists():
            keep_ids.update(row["document_id"] for row in json.loads(issues.read_text()))
        successful = set()
        for benchmark_path in [root / "benchmark_final/benchmark.json", root / "benchmark/benchmark.json"]:
            if benchmark_path.exists():
                for row in json.loads(benchmark_path.read_text())["results"]:
                    engine = row["engines"]["candidate"]
                    if engine.get("success") and not engine.get("execution_error"):
                        successful.add(row["document_id"])
        # Successful unlabelled samples can be dropped after a complete decision;
        # regression originals and source-backed review cases stay available.
        for manifest in [root / "sample/manifest.json", root / "sample_001/manifest.json"]:
            if not manifest.exists():
                continue
            for row in json.loads(manifest.read_text()):
                path = Path(row["source_path"]).resolve()
                if (
                    row["document_id"] in successful
                    and row["document_id"] not in keep_ids
                    and path.is_relative_to(root)
                ):
                    paths.append(path)
        # Keep compact benchmark measurements and reviewed/failing cases, not
        # full parsed bodies for every ordinary successful document.
        for name in ("benchmark", "benchmark_final", "timing_confirmation"):
            directory = root / name
            benchmark_path = directory / "benchmark.json"
            if not benchmark_path.exists():
                continue
            for row in json.loads(benchmark_path.read_text())["results"]:
                identifier = row["document_id"]
                if identifier in keep_ids or Path(identifier).name != identifier:
                    continue
                engines = row["engines"]
                if not engines or not all(
                    engine.get("success") and not engine.get("execution_error") for engine in engines.values()
                ):
                    continue
                paths.extend(
                    (directory / identifier / (engine + ".json"))
                    for engine in ("baseline", "candidate", "kordoc")
                )
        if (root / "benchmark_final/benchmark.json").exists() or (root / "benchmark/benchmark.json").exists():
            paths.append(root / "discovery")
        replay = root / "historical_regression"
        if (replay / "report.json").exists():
            # The source/version manifest and report survive; full replay bodies
            # are regenerable from the fixed originals and frozen parser sources.
            paths.extend(p for p in replay.glob("*.json") if p.name not in {"report.json", "progress.json"})
        for replay in (root / "regression", root / "historical_regression"):
            report_path = replay / "report.json"
            if not report_path.exists():
                continue
            report = json.loads(report_path.read_text())
            if report.get("status") != "complete":
                continue
            for row in report.get("results", []):
                identifier = row["document_id"]
                if (
                    Path(identifier).name == identifier
                    and row.get("equal_except_version")
                    and row.get("before_success")
                    and row.get("after_success")
                ):
                    paths.extend(
                        replay / identifier / (engine + ".json") for engine in ("baseline", "candidate")
                    )
        plan = remove_paths(paths, protected, apply=apply)
        result = {
            "schema_version": 1,
            "status": "cleaned" if apply else "planned",
            "created_at": datetime.now(UTC).isoformat(),
            "cycle_root": str(root),
            "removed_bytes": sum(row.get("allocated_bytes", 0) for row in plan if row["status"] == "removed"),
            "paths": plan,
            "preserved": "Regression originals, labelled/problem cases, manifests, hashes, reports and frozen source snapshots",
        }
        if apply:
            removed = {row["path"] for row in plan if row["status"] == "removed"}
            for entry in history.state["documents"].values():
                if entry.get("source_path") in removed:
                    entry["retention"] = "removed_after_completed_cycle"
                    entry["removed_at"] = result["created_at"]
            history.save()
            atomic_json(root / "cleanup.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--cycle-root", type=Path)
    scope.add_argument("--legacy-environments", action="store_true")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.legacy_environments:
        with CorpusHistory(args.history) as history:
            history.regression_bytes()
            protected = protected_sources(history.state)
            protected.update(
                Path(row["source_path"]).resolve()
                for row in history.state["documents"].values()
                if row.get("source_path")
            )
            paths = remove_paths(legacy_environments(), protected, apply=args.apply)
            result = {
                "schema_version": 1,
                "status": "cleaned" if args.apply else "planned",
                "removed_bytes": sum(
                    row.get("allocated_bytes", 0) for row in paths if row["status"] == "removed"
                ),
                "paths": paths,
            }
    else:
        result = cleanup_cycle(args.cycle_root, apply=args.apply, history_path=args.history)
    if args.output:
        atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "removed_bytes": result["removed_bytes"],
                "planned_bytes": sum(
                    row.get("allocated_bytes", 0) for row in result["paths"] if row["status"] == "planned"
                ),
                "paths": len(result["paths"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
