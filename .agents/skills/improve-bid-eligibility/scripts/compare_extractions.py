#!/usr/bin/env python3
"""Compare a sealed source review with a fresh normalized extraction."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


REQUIREMENT_FIELDS = (
    "type", "operator", "value", "original_text", "proposition_text",
    "proposition_start", "proposition_end", "holder_scope", "reference_date_type",
    "assessment_stage", "failure_effect", "comparison_mode", "mandatory",
    "review_status", "evidence", "proof_requirements", "standard_rule_id",
    "standard_rule_version", "rule_arguments", "logic",
)


def _normalized(value):
    if isinstance(value, dict):
        return {key: _normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        items = [_normalized(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ))
    return value


def _project(requirement: dict, expected: dict) -> dict:
    return {
        field: _normalized(requirement.get(field))
        for field in REQUIREMENT_FIELDS if field in expected
    }


def _match_requirements(expected: list[dict], actual: list[dict]) -> tuple[list, list, int]:
    unmatched = list(actual)
    missing = []
    matched = 0
    for requirement in expected:
        target = _project(requirement, requirement)
        index = next(
            (i for i, observed in enumerate(unmatched)
             if _project(observed, requirement) == target),
            None,
        )
        if index is None:
            missing.append(target)
        else:
            matched += 1
            unmatched.pop(index)
    return missing, unmatched, matched


def _evidence_identity(requirement: dict) -> set[tuple]:
    return {
        (item.get("source_type"), item.get("source_id"), item.get("document_id"),
         item.get("block_id"))
        for item in requirement.get("evidence", [])
    }


def _pair_requirements(expected: list[dict], actual: list[dict]) -> tuple[list, list, list]:
    """Pair source-equivalent facts before reporting field-level semantic differences."""
    remaining = list(actual)
    paired = []
    missing = []
    for wanted in expected:
        target = _project(wanted, wanted)
        exact = next((i for i, item in enumerate(remaining)
                      if _project(item, wanted) == target), None)
        basis = "exact"
        if exact is None:
            wanted_evidence = _evidence_identity(wanted)
            exact = next((i for i, item in enumerate(remaining)
                          if item.get("type") == wanted.get("type")
                          and wanted_evidence
                          and wanted_evidence & _evidence_identity(item)), None)
            basis = "same_type_and_evidence"
        if exact is None:
            missing.append(target)
            continue
        observed = remaining.pop(exact)
        differences = {
            field: {"expected": _normalized(wanted.get(field)),
                    "actual": _normalized(observed.get(field))}
            for field in REQUIREMENT_FIELDS if field in wanted
            and _normalized(wanted.get(field)) != _normalized(observed.get(field))
        }
        paired.append({
            "matching_basis": basis,
            "expected_type": wanted.get("type"),
            "actual_id": observed.get("id"),
            "field_differences": differences,
        })
    return paired, missing, remaining


def _validate_seal(case_path: Path, seal_path: Path | None) -> list[str]:
    case = json.loads(case_path.read_text())
    if case["partition"] == "regression" and seal_path is None:
        return []
    if seal_path is None:
        return ["source_review_seal_required"]
    seal = json.loads(seal_path.read_text())
    digest = hashlib.sha256(case_path.read_bytes()).hexdigest()
    errors = []
    if seal.get("sha256") != digest:
        errors.append("source_review_changed_after_seal")
    if seal.get("case_id") != case["case_id"]:
        errors.append("source_review_seal_case_mismatch")
    return errors


def _validate_manifest(actual_path: Path, case: dict, manifest_path: Path | None) -> list[str]:
    if case["partition"] == "regression" and manifest_path is None:
        return []
    if manifest_path is None:
        return ["revealed_manifest_required"]
    manifest = json.loads(manifest_path.read_text())
    item = next((item for item in manifest["cases"] if (
        item["notice_number"], item["notice_order"]
    ) == (case["notice"]["notice_number"], case["notice"]["notice_order"])), None)
    if item is None or item.get("status") != "completed":
        return ["fresh_extraction_not_revealed"]
    if item.get("output") != actual_path.name:
        return ["manifest_output_mismatch"]
    return []


def _schema_errors(actual: dict) -> list[str]:
    schema_path = (Path(__file__).parents[2] / "extract-bid-eligibility" /
                   "references/eligibility-extraction.schema.json")
    schema = json.loads(schema_path.read_text())
    errors = []
    for error in Draft202012Validator(schema).iter_errors(actual):
        location = ".".join(map(str, error.path)) or "$"
        errors.append(f"{location}:{error.message}")
    for index, item in enumerate(actual.get("requirements", [])):
        original = item.get("original_text", "")
        proposition = item.get("proposition_text", "")
        start = item.get("proposition_start")
        end = item.get("proposition_end")
        if not isinstance(start, int) or not isinstance(end, int) or original[start:end] != proposition:
            errors.append(f"requirements.{index}:invalid_proposition_span")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    case = json.loads(args.case.read_text())
    actual = json.loads(args.actual.read_text())
    expected_items = case["expected"]["requirements"]
    actual_items = actual.get("requirements", [])
    paired, missing, unexpected = _pair_requirements(expected_items, actual_items)
    matched = sum(not item["field_differences"] for item in paired)
    semantic_mismatches = [item for item in paired if item["field_differences"]]
    expected_unresolved = Counter(
        json.dumps(_normalized(item), ensure_ascii=False, sort_keys=True)
        for item in case["expected"]["unresolved_candidates"]
    )
    actual_unresolved = Counter(
        json.dumps(_normalized(item), ensure_ascii=False, sort_keys=True)
        for item in actual.get("unresolved_candidates", [])
    )
    missing_unresolved = [json.loads(item) for item in
                          (expected_unresolved - actual_unresolved).elements()]
    unexpected_unresolved = [json.loads(item) for item in
                             (actual_unresolved - expected_unresolved).elements()]
    expected_expression = case["expected"].get("expression")
    expression_matches = (
        None if expected_expression is None
        else _normalized(expected_expression) == _normalized(actual.get("expression"))
    )
    integrity_errors = [
        *_validate_seal(args.case, args.seal),
        *_validate_manifest(args.actual, case, args.manifest),
        *_schema_errors(actual),
    ]
    passed = not any((missing, unexpected, semantic_mismatches, missing_unresolved,
                      unexpected_unresolved, integrity_errors))
    if expression_matches is False:
        passed = False
    report = {
        "case_id": case["case_id"],
        "partition": case["partition"],
        "expected_count": len(expected_items),
        "actual_count": len(actual_items),
        "matched_count": matched,
        "paired_count": len(paired),
        "semantic_mismatches": semantic_mismatches,
        "missing": missing,
        "unexpected": unexpected,
        "missing_unresolved": missing_unresolved,
        "unexpected_unresolved": unexpected_unresolved,
        "expression_matches": expression_matches,
        "integrity_errors": integrity_errors,
        "passed": passed,
        "earliest_layer": case["classification"]["earliest_layer"],
        "severity": case["classification"]["severity"],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(text)
    else:
        print(text, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
