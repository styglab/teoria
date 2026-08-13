#!/usr/bin/env python3
"""Aggregate comparison reports into reproducible evaluation metrics."""

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    reports = [json.loads(path.read_text()) for path in args.reports]
    partitions = Counter(item["partition"] for item in reports)
    layers = Counter(item["earliest_layer"] for item in reports if not item["passed"])
    severities = Counter(item["severity"] for item in reports if not item["passed"])
    expected = sum(item["expected_count"] for item in reports)
    matched = sum(item["matched_count"] for item in reports)
    summary = {
        "cases": len(reports),
        "passed_cases": sum(item["passed"] for item in reports),
        "failed_cases": sum(not item["passed"] for item in reports),
        "partitions": dict(sorted(partitions.items())),
        "failures_by_earliest_layer": dict(sorted(layers.items())),
        "failures_by_severity": dict(sorted(severities.items())),
        "expected_requirements": expected,
        "matched_requirements": matched,
        "requirement_recall": None if expected == 0 else round(matched / expected, 6),
        "unexpected_requirements": sum(len(item["unexpected"]) for item in reports),
        "missing_unresolved_candidates": sum(
            len(item.get("missing_unresolved", [])) for item in reports
        ),
        "unexpected_unresolved_candidates": sum(
            len(item.get("unexpected_unresolved", [])) for item in reports
        ),
        "expression_failures": sum(
            item.get("expression_matches") is False for item in reports
        ),
        "integrity_errors": sum(
            len(item.get("integrity_errors", [])) for item in reports
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
