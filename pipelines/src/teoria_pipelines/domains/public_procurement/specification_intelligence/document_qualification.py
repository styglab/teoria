"""Validate saved document-qualification proposals without model or network calls."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .document_evidence import EvidenceQuote, ParsedEvidenceDocument, validate_evidence


DocumentRole = Literal["procurement_specification", "statement_of_work", "notice", "product_catalog", "form", "mixed", "other", "unknown"]


class QualificationRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_id: str = Field(min_length=1)
    decision: Literal["REQUIREMENTS_FOUND", "NO_REQUIREMENTS_FOUND", "AMBIGUOUS"]
    evidence: list[EvidenceQuote]
    reason: str = Field(min_length=1)


class QualificationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_role: DocumentRole
    regions: list[QualificationRegion]
    summary: str


def validate_qualification(proposal: QualificationProposal, document: ParsedEvidenceDocument) -> dict:
    if len({r.region_id for r in proposal.regions}) != len(proposal.regions):
        raise ValueError("duplicate qualification region")
    regions = []
    for r in proposal.regions:
        errors = validate_evidence(r.evidence, [document])
        regions.append({**r.model_dump(), "evidence_errors": errors,
                        "eligible_for_analysis": r.decision == "REQUIREMENTS_FOUND" and not errors})
    found = any(r["eligible_for_analysis"] for r in regions)
    ambiguous = any(r["decision"] == "AMBIGUOUS" or r["evidence_errors"] for r in regions)
    if found:
        decision = "REQUIREMENTS_FOUND"
    elif document.unreadable_refs or not regions:
        decision = "UNASSESSABLE" if not any(n.kind != "image" and n.text.strip() for n in document.nodes) else "AMBIGUOUS"
    elif ambiguous:
        decision = "AMBIGUOUS"
    else:
        decision = "NO_REQUIREMENTS_FOUND_IN_REVIEWED_INPUT"
    return {
        "document_id": document.document_id, "parse_run_id": document.parse_run_id,
        "native_sha256": document.native_sha256, "decision": decision,
        "document_role": proposal.document_role, "regions": regions,
        "unassessed_native_refs": list(document.unreadable_refs),
        "scope": "supplied_parse_only", "review_status": "pending",
        "summary": proposal.summary,
    }


class QualificationSubmission(BaseModel):
    """Codex-authored proposal bound to immutable input bytes."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["qualification_submission_v1"] = "qualification_submission_v1"
    run_id: str = Field(min_length=1)
    analysis_method: Literal["codex_interactive_reading"]
    document_id: str = Field(min_length=1)
    parse_run_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal: QualificationProposal


class ValidatedQualificationRegion(QualificationRegion):
    evidence_errors: list[str]
    eligible_for_analysis: bool


class QualificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    parse_run_id: str
    native_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["REQUIREMENTS_FOUND", "UNASSESSABLE", "AMBIGUOUS", "NO_REQUIREMENTS_FOUND_IN_REVIEWED_INPUT"]
    document_role: DocumentRole
    regions: list[ValidatedQualificationRegion]
    unassessed_native_refs: list[str]
    scope: Literal["supplied_parse_only"]
    review_status: Literal["pending"]
    summary: str


class QualificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["qualification_record_v1"] = "qualification_record_v1"
    submission: QualificationSubmission
    result: QualificationResult


def validate_qualification_submission(
    submission: QualificationSubmission, document: ParsedEvidenceDocument,
) -> QualificationRecord:
    expected = (document.document_id, document.parse_run_id, document.native_sha256)
    actual = (submission.document_id, submission.parse_run_id, submission.native_sha256)
    if actual != expected:
        raise ValueError("qualification input identity mismatch")
    return QualificationRecord(
        submission=submission,
        result=QualificationResult.model_validate(validate_qualification(submission.proposal, document)),
    )


def main() -> None:
    """Offline file entry point; writes a new record and never calls a model."""
    import argparse
    import hashlib
    import json
    from pathlib import Path
    from .document_evidence import build_document_evidence

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        submission = QualificationSubmission.model_validate_json(args.submission.read_bytes())
        raw = args.native.read_bytes()
        document = build_document_evidence(
            json.loads(raw), document_id=submission.document_id,
            parse_run_id=submission.parse_run_id, native_sha256=hashlib.sha256(raw).hexdigest(),
        )
        record = validate_qualification_submission(submission, document)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(record.model_dump_json(indent=2) + "\n")
    except (ValueError, OSError) as error:
        parser.exit(2, f"qualification failed: {error}\n")
    print(json.dumps({"decision": record.result.decision, "review_status": record.result.review_status}))


if __name__ == "__main__":
    main()
