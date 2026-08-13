#!/usr/bin/env python3
"""Seal a source-derived evaluation case before extraction output is revealed."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


EXPECTED_REQUIREMENT_FIELDS = {
    "type", "operator", "value", "holder_scope", "reference_date_type",
    "assessment_stage", "failure_effect", "mandatory", "evidence",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--source-input", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    args = parser.parse_args()
    skill_root = Path(__file__).parents[1]
    schema = json.loads((skill_root / "references/evaluation-case.schema.json").read_text())
    case_bytes = args.case.read_bytes()
    case = json.loads(case_bytes)
    errors = list(Draft202012Validator(
        schema, format_checker=FormatChecker(),
    ).iter_errors(case))
    if errors:
        for error in errors:
            location = ".".join(map(str, error.path)) or "$"
            print(f"{args.case}:{location}: {error.message}")
        return 1
    if case["provenance"]["expectation_method"] != "independent_source_review":
        raise ValueError("source_review_must_be_independent")
    source_bytes = args.source_input.read_bytes()
    source = json.loads(source_bytes)
    blocks = {}
    for document in source.get("documents", []):
        for block in document.get("content", {}).get("blocks", []):
            blocks[(str(document.get("document_id")), str(block.get("block_id")))] = str(
                block.get("text") or ""
            )
    structured = {
        str(item.get("source_id")): json.dumps(item, ensure_ascii=False)
        for item in source.get("structured_requirements", [])
    }
    evidence_errors = []
    for requirement in case["expected"]["requirements"]:
        missing = EXPECTED_REQUIREMENT_FIELDS - requirement.keys()
        if missing or not requirement.get("evidence"):
            raise ValueError(
                "incomplete_expected_requirement:" + ",".join(sorted(missing))
            )
        for evidence in requirement.get("evidence", []):
            excerpt = str(evidence.get("excerpt") or "")
            if evidence.get("source_type") == "document":
                text = blocks.get((str(evidence.get("document_id")),
                                   str(evidence.get("block_id"))))
                if text is None or excerpt not in text:
                    evidence_errors.append("document_evidence_not_in_source")
            elif excerpt not in structured.get(str(evidence.get("source_id")), ""):
                evidence_errors.append("structured_evidence_not_in_source")
        for proof in requirement.get("proof_requirements", []):
            for evidence in proof.get("evidence", []):
                excerpt = str(evidence.get("excerpt") or "")
                if evidence.get("source_type") == "document":
                    text = blocks.get((str(evidence.get("document_id")),
                                       str(evidence.get("block_id"))))
                    if text is None or excerpt not in text:
                        evidence_errors.append("proof_evidence_not_in_source")
                elif excerpt not in structured.get(str(evidence.get("source_id")), ""):
                    evidence_errors.append("proof_structured_evidence_not_in_source")
    if evidence_errors:
        raise ValueError(",".join(sorted(set(evidence_errors))))
    seal = {
        "case_id": case["case_id"],
        "notice_number": case["notice"]["notice_number"],
        "notice_order": case["notice"]["notice_order"],
        "sha256": hashlib.sha256(case_bytes).hexdigest(),
        "source_input_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    args.seal.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
