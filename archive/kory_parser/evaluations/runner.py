"""Pinned source-oracle evaluation. Reports contain IDs and scores, not document text."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import zipfile
from importlib.metadata import version
from pathlib import Path

from kory_parser.compare import compare_results, normalized_text
from kory_parser.models import ParseOptions

from .execution import run_process

PROJECT = Path(__file__).resolve().parents[1]
METRICS = (
    "success",
    "text_precision",
    "text_recall",
    "reading_order",
    "table_structure",
    "table_cells",
    "contents",
    "block_structure",
)
WORKER = """
import json, sys, time, statistics
from pathlib import Path
from kory_parser import parse, ParseOptions
request = json.load(sys.stdin)
data = Path(request['source']).read_bytes()
requested = dict(request['options'])
supported = 'recover_numbered_structure' in getattr(ParseOptions, '__dataclass_fields__', {})
if not supported:
    requested.pop('recover_numbered_structure', None)
options = ParseOptions(**requested)
parse(data, options)
samples = []
for _ in range(3):
    start = time.perf_counter()
    result = parse(data, options)
    samples.append(time.perf_counter() - start)
seconds = statistics.median(samples)
Path(request['output']).write_text(json.dumps(result.to_dict(), ensure_ascii=False))
print(json.dumps({'seconds': seconds, 'samples': samples}))
"""
SCORE_WORKER = """
import json, sys
from evaluations.runner import score
request = json.load(sys.stdin)
print(json.dumps(score(request['expected'], request['actual'])))
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix
            in {
                ".py",
                ".json",
                ".toml",
                ".js",
                ".mjs",
                ".cjs",
                ".sql",
            }
        ):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def fixture_bytes(parts):
    """Stable ZIP bytes: no wall-clock timestamps or host-dependent compression."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, content.encode("utf-8"))
    return stream.getvalue()


def load_manifest(path):
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or not manifest.get("corpus_version"):
        raise ValueError("Manifest requires schema_version=1 and corpus_version")
    if not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("Manifest requires nonempty cases")
    thresholds = manifest.get("thresholds", {})
    if set(thresholds) - set(METRICS):
        raise ValueError("Unknown metric threshold")
    for value in thresholds.values():
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Thresholds must be finite numbers in [0, 1]")
    seen = set()
    input_splits = {}
    for case in manifest["cases"]:
        identifier = case["id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier) or identifier in seen:
            raise ValueError("Case IDs must be unique snake_case")
        seen.add(identifier)
        if case.get("split") not in {"development", "validation"}:
            raise ValueError("Each case needs development/validation split")
        if not re.fullmatch(r"[a-f0-9]{64}", case.get("sha256", "")):
            raise ValueError("Each case needs an input sha256")
        if input_splits.setdefault(case["sha256"], case["split"]) != case["split"]:
            raise ValueError("The same input cannot appear in both splits")
        if not case.get("evidence"):
            raise ValueError("Each case needs source-oracle evidence")
        if ("parts" in case) == ("source_path" in case):
            raise ValueError("Choose parts or source_path")
        if case.get("format") not in {"hwpx", "docx", "xlsx", "pptx", "pdf", "hwp", "png", "jpg", "xls"}:
            raise ValueError("Unsupported case format")
        expected = case["expected"]
        if expected.get("success") is not True and expected.get("success") is not False:
            raise ValueError("Expected success must be boolean")
        if expected["success"] and not isinstance(expected.get("blocks"), list):
            raise ValueError("Successful cases need independently authored expected blocks")
        if not expected["success"] and not expected.get("error_code"):
            raise ValueError("Failure cases need expected error_code")
        options = case.get("options", {})
        ParseOptions(**options)
        limit = case.get("max_seconds", 30)
        if not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0:
            raise ValueError("max_seconds must be finite and positive")
    return manifest


def input_bytes(case, corpus_root):
    if "parts" in case:
        data = fixture_bytes(case["parts"])
    else:
        relative = Path(case["source_path"])
        path = (corpus_root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(corpus_root.resolve()):
            raise ValueError("source_path must stay within corpus root")
        data = path.read_bytes()
    if sha(data) != case["sha256"]:
        raise ValueError(f"Input checksum mismatch: {case['id']}")
    return data


def contents_signature(contents):
    return [
        [
            (
                normalized_text(e["title"]),
                e.get("number"),
                e.get("level"),
                e.get("printed_page_label"),
                e.get("target_status"),
            )
            for e in item["entries"]
        ]
        for item in contents
    ]


def score(expected, actual):
    status = expected["success"] == actual.get("success")
    if not expected["success"]:
        return {"success": float(status and expected["error_code"] == actual.get("error_code"))}
    comparison = compare_results(expected, actual)
    metrics = {
        "success": float(status),
        "text_precision": comparison["character_multiset_precision"],
        "text_recall": comparison["character_multiset_recall"],
        "reading_order": comparison["reading_order_similarity"],
        "table_structure": float(comparison["all_table_grids_equal"]),
        "table_cells": float(comparison["all_tables_and_cells_equal"]),
    }
    if expected.get("require_block_structure"):
        from .numbered_structure import structure_signature

        metrics["block_structure"] = float(
            structure_signature(expected["blocks"]) == structure_signature(actual.get("blocks", []))
        )
    if "contents" in expected:
        metrics["contents"] = float(
            contents_signature(expected["contents"]) == contents_signature(actual.get("contents", []))
        )
    return metrics


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def evaluate(manifest_path, output, *, candidate=PROJECT, corpus_root=None, split="all", deadline=None):
    """Run pinned evaluator against candidate source in separate, timed workers."""
    manifest_path, candidate, output = manifest_path.resolve(), candidate.resolve(), output.resolve()
    manifest = load_manifest(manifest_path)
    cases = [c for c in manifest["cases"] if split == "all" or c["split"] == split]
    if not cases:
        raise ValueError("Selected split is empty")
    root = (corpus_root or manifest_path.parent).resolve()
    # Check the entire selected input set before executing any candidate code.
    inputs = {c["id"]: input_bytes(c, root) for c in cases}
    output.mkdir(parents=True, exist_ok=False)
    source_hash = tree_digest(candidate / "src")
    evaluator_hash = tree_digest(Path(__file__).parent)
    env = dict(os.environ, PYTHONPATH=str(candidate / "src"))
    rows = []
    for case in cases:
        directory = output / case["id"]
        directory.mkdir()
        source = directory / ("input." + case["format"])
        source.write_bytes(inputs[case["id"]])
        native = directory / "parsed.json"
        timeout = float(case.get("max_seconds", 30))
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("Evaluation time budget exhausted")
        case_deadline = time.monotonic() + timeout
        seconds, error, samples, actual_success = None, None, [], False
        try:
            run = run_process(
                [sys.executable, "-c", WORKER],
                cwd=candidate,
                env=env,
                timeout=timeout,
                input=json.dumps(
                    {"source": str(source), "output": str(native), "options": case.get("options", {})}
                ),
            )
            if run.returncode:
                raise RuntimeError("Parser worker failed")
            actual = json.loads(native.read_text())
            measurement = json.loads(run.stdout)
            seconds = measurement["seconds"]
            samples = measurement["samples"]
            actual_success = actual.get("success", False)
            # Sequence comparison can be expensive on repetitive documents. Run
            # the original evaluator, not the candidate's copy, within the same budget.
            scored = run_process(
                [sys.executable, "-c", SCORE_WORKER],
                cwd=PROJECT,
                env=dict(os.environ, PYTHONPATH=os.pathsep.join((str(PROJECT), str(PROJECT / "src")))),
                timeout=max(0.001, case_deadline - time.monotonic()),
                input=json.dumps({"expected": case["expected"], "actual": actual}),
            )
            if scored.returncode:
                raise RuntimeError("Scoring worker failed")
            metrics = json.loads(scored.stdout)
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            error = type(exc).__name__
            metrics = {"success": 0.0}
        failures = [
            name for name, value in metrics.items() if value < manifest.get("thresholds", {}).get(name, 1)
        ]
        if error:
            failures.append("execution")
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "input_sha256": case["sha256"],
                "options": case.get("options", {}),
                "metrics": metrics,
                "seconds": seconds,
                "timing_samples": samples,
                "parse_success": actual_success,
                "failures": failures,
                "error": error,
                "passed": not failures,
            }
        )
    if source_hash != tree_digest(candidate / "src"):
        raise ValueError("Candidate changed during evaluation")
    if evaluator_hash != tree_digest(Path(__file__).parent):
        raise ValueError("Evaluator changed during evaluation")
    report = {
        "schema_version": 1,
        "corpus_version": manifest["corpus_version"],
        "manifest_sha256": sha(manifest_path.read_bytes()),
        "source_sha256": source_hash,
        "evaluator_sha256": evaluator_hash,
        "lock_sha256": sha((candidate / "uv.lock").read_bytes()),
        "python": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in (
                "kory-parser",
                "pymupdf",
                "defusedxml",
                "olefile",
                "fonttools",
                "Pillow",
                "xlrd",
            )
        },
        "split": split,
        "timing_policy": {
            "warmups": 1,
            "repetitions": 3,
            "aggregate_max_ratio": 1.05,
            "document_max_ratio": 1.15,
            "document_min_delta_seconds": 0.01,
        },
        "cases": rows,
        "passed": all(row["passed"] for row in rows),
        "interpretation": "Source-oracle checks; synthetic seed coverage is not real-document accuracy.",
    }
    write_json(output / "report.json", report)
    lines = [
        "# Kory Parser evaluation",
        "",
        report["interpretation"],
        "",
        "| Case | Split | Pass | Failed checks | Seconds |",
        "|---|---|---|---|---:|",
    ]
    lines.extend(
        f"| {r['id']} | {r['split']} | {r['passed']} | {', '.join(r['failures'])} | {r['seconds']} |"
        for r in rows
    )
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return report


def compare_reports(baseline, candidate):
    if baseline.get("timing_policy") != candidate.get("timing_policy"):
        raise ValueError("Incomparable reports: timing_policy")
    for key in ("manifest_sha256", "evaluator_sha256", "lock_sha256", "python", "dependencies", "split"):
        if baseline[key] != candidate[key]:
            raise ValueError(f"Incomparable reports: {key}")
    left, right = ({row["id"]: row for row in report["cases"]} for report in (baseline, candidate))
    if left.keys() != right.keys():
        raise ValueError("Incomparable case sets")
    regressions, improvements = [], []
    timing_totals = [0.0, 0.0]
    for identifier, before in left.items():
        after = right[identifier]
        if before["input_sha256"] != after["input_sha256"] or before["options"] != after["options"]:
            raise ValueError("Incomparable case identity")
        for metric in before["metrics"].keys() | after["metrics"].keys():
            old, new = before["metrics"].get(metric, 0), after["metrics"].get(metric, 0)
            if new < old:
                regressions.append(f"{identifier}:{metric}")
            elif new > old:
                improvements.append(f"{identifier}:{metric}")
        if before["passed"] and not after["passed"]:
            regressions.append(f"{identifier}:gate")
        if before.get("parse_success") and after.get("parse_success"):
            old_seconds, new_seconds = before.get("seconds"), after.get("seconds")
            if old_seconds is None or new_seconds is None:
                regressions.append(f"{identifier}:timing_unavailable")
            else:
                timing_totals[0] += old_seconds
                timing_totals[1] += new_seconds
                if new_seconds > old_seconds * 1.15 and new_seconds - old_seconds > 0.01:
                    regressions.append(f"{identifier}:timing_requires_confirmation")
    if timing_totals[0] and timing_totals[1] > timing_totals[0] * 1.05:
        regressions.append("aggregate_timing_regression")
    return {
        "regressions": regressions,
        "improvements": improvements,
        "accepted": bool(improvements) and not regressions,
        "timing_totals": timing_totals,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT / "evaluations/corpus/seed.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=PROJECT)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--split", choices=("all", "development", "validation"), default="all")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(
            args.manifest,
            args.output,
            candidate=args.candidate,
            corpus_root=args.corpus_root,
            split=args.split,
        )
        if args.baseline:
            comparison = compare_reports(json.loads(args.baseline.read_text()), report)
            write_json(args.output / "comparison.json", comparison)
            print(json.dumps(comparison))
            return 1 if comparison["regressions"] else 0
        print(json.dumps({"passed": report["passed"], "cases": len(report["cases"])}))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, KeyError, TimeoutError) as error:
        print(f"Evaluation failed: {type(error).__name__}", file=sys.stderr)
        return 2
