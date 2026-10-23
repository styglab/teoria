"""Accept and optionally apply a candidate only after quality, regression and timing gates."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from ..execution import run_process
from ..runner import PROJECT, sha, tree_digest, write_json


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items() if k != "parser_version"}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def assess(benchmark_dir, quality, policy, confirmation=None):
    benchmark = json.loads((benchmark_dir / "benchmark.json").read_text())
    if (
        quality.get("benchmark_manifest_sha256") != benchmark["manifest_sha256"]
        or quality.get("benchmark_source_hashes") != benchmark["source_hashes"]
    ):
        raise ValueError("Quality report and benchmark identity mismatch")
    failures = []
    if quality["regressions"]:
        failures.append("source_quality_regression")
    if not quality["improvements"]:
        failures.append("no_source_quality_improvement")
    changed = []
    totals = {"baseline": 0.0, "candidate": 0.0}
    warnings = []
    targets = {item.split(":", 1)[0] for item in quality["improvements"]}
    reference = {r["document_id"]: r for r in confirmation["results"]} if confirmation else {}
    if confirmation and confirmation["source_hashes"] != benchmark["source_hashes"]:
        raise ValueError("Confirmation uses different source snapshots")
    for row in benchmark["results"]:
        identifier = row["document_id"]
        engines = row["engines"]
        before, after = engines["baseline"], engines["candidate"]
        if any(e.get("execution_error") for e in engines.values()):
            failures.append(identifier + ":execution_error")
        if before["success"] and not after["success"]:
            failures.append(identifier + ":success_regression")
        b = json.loads((benchmark_dir / identifier / "baseline.json").read_text())
        c = json.loads((benchmark_dir / identifier / "candidate.json").read_text())
        if canonical(b) != canonical(c):
            changed.append(identifier)
            if identifier not in targets:
                failures.append(identifier + ":unreviewed_output_change")
        if before["success"] and after["success"]:
            totals["baseline"] += before["median_seconds"]
            totals["candidate"] += after["median_seconds"]
            rules = policy["timing"]

            def slower(old, new, rules=rules):
                return (
                    new > old * rules["per_document_ratio_warning"]
                    and new - old > rules["per_document_absolute_warning_seconds"]
                )

            if slower(before["median_seconds"], after["median_seconds"]):
                check = reference.get(identifier)
                if (
                    not check
                    or check["sha256"] != row["sha256"]
                    or confirmation["repetitions"] < rules["confirmation_repetitions"]
                ):
                    failures.append(identifier + ":timing_confirmation_required")
                    warnings.append(identifier)
                elif slower(
                    check["engines"]["baseline"]["median_seconds"],
                    check["engines"]["candidate"]["median_seconds"],
                ):
                    failures.append(identifier + ":confirmed_timing_regression")
                    warnings.append(identifier)
    ratio = totals["candidate"] / totals["baseline"] if totals["baseline"] else None
    if ratio is None or ratio > policy["timing"]["aggregate_max_ratio"]:
        failures.append("aggregate_timing_regression_or_unavailable")
    return {
        "accepted": not failures,
        "failures": failures,
        "changed_documents": changed,
        "unresolved_timing_warnings": warnings,
        "successful_document_median_sum_seconds": totals,
        "candidate_to_baseline_time_ratio": ratio,
        "source_hashes": benchmark["source_hashes"],
    }


def apply_source(project, candidate, hashes):
    if (
        tree_digest(project / "src") != hashes["baseline"]
        or tree_digest(candidate / "src") != hashes["candidate"]
    ):
        raise ValueError("Source changed since the benchmark; refuse apply")
    old = {
        p.relative_to(project / "src"): p
        for p in (project / "src").rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    new = {
        p.relative_to(candidate / "src"): p
        for p in (candidate / "src").rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    for source in [*old.values(), *new.values()]:
        if source.is_symlink():
            raise ValueError("Symlink in source snapshot")
    for relative, path in new.items():
        destination = project / "src" / relative
        if destination.exists() and destination.read_bytes() == path.read_bytes():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_suffix(destination.suffix + ".candidate_tmp")
        shutil.copyfile(path, staging)
        staging.replace(destination)
    for relative, path in old.items():
        if relative not in new:
            path.unlink()
    if tree_digest(project / "src") != hashes["candidate"]:
        raise ValueError("Applied source verification failed")


def fixed_regression_check(cycle, benchmark, historical):
    if (
        cycle.get("status") != "complete"
        or cycle.get("fresh_manifest_sha256") != benchmark["manifest_sha256"]
    ):
        return "incomplete_or_unrelated_sampling_cycle"
    regression = cycle["datasets"]["regression"]
    if sha(Path(regression["path"]).read_bytes()) != regression["sha256"]:
        return "fixed_regression_manifest_changed"
    if not historical:
        return "fixed_regression_replay_required"
    if (
        historical.get("status") != "complete"
        or historical.get("manifest_sha256") != regression["sha256"]
        or historical.get("baseline_source_sha256") != benchmark["source_hashes"]["baseline"]
        or historical.get("candidate_source_sha256") != benchmark["source_hashes"]["candidate"]
        or historical.get("documents") != len(json.loads(Path(regression["path"]).read_text()))
        or historical["documents"] != historical.get("equal_except_version")
    ):
        return "fixed_regression_failed_or_identity_mismatch"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--historical-report", type=Path)
    parser.add_argument("--cycle-manifest", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    benchmark = json.loads((args.benchmark / "benchmark.json").read_text())
    candidate = args.candidate.resolve()
    if tree_digest(candidate / "src") != benchmark["source_hashes"]["candidate"]:
        raise ValueError("Candidate differs from benchmark")
    quality = json.loads(args.quality.read_text())
    policy = json.loads(args.policy.read_text())
    confirmation = json.loads(args.confirmation.read_text()) if args.confirmation else None
    result = assess(args.benchmark, quality, policy, confirmation)
    historical = json.loads(args.historical_report.read_text()) if args.historical_report else None
    cycle_path = args.cycle_manifest
    if cycle_path is None and benchmark.get("manifest_path"):
        adjacent = Path(benchmark["manifest_path"]).parent / "cycle_manifest.json"
        if adjacent.exists():
            cycle_path = adjacent
    if cycle_path:
        reason = fixed_regression_check(json.loads(cycle_path.read_text()), benchmark, historical)
        if reason:
            result["failures"].append(reason)
            result["accepted"] = False
    if args.historical_report:
        result["historical_regression"] = {
            key: historical[key] for key in ("documents", "equal_except_version")
        }
        if (
            historical.get("candidate_source_sha256") != benchmark["source_hashes"]["candidate"]
            or historical["documents"] != historical["equal_except_version"]
        ):
            result["failures"].append("historical_regression_or_identity_mismatch")
            result["accepted"] = False
    tests = run_process(
        [sys.executable, "-m", "pytest", "-q", "-c", str(PROJECT / "pyproject.toml"), str(PROJECT / "tests")],
        cwd=PROJECT,
        env=dict(os.environ, PYTHONPATH=str(candidate / "src")),
        timeout=180,
    )
    (args.output / "tests.log").write_text(tests.stdout + tests.stderr)
    result["tests_passed"] = tests.returncode == 0
    result["applied"] = False
    if tests.returncode:
        result["failures"].append("unit_tests_failed")
        result["accepted"] = False
    write_json(args.output / "acceptance.json", result)
    if result["accepted"] and args.apply:
        apply_source(PROJECT, candidate, result["source_hashes"])
        result["applied"] = True
        write_json(args.output / "acceptance.json", result)
    print(json.dumps(result))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
