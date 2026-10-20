"""Final review and repair lineage for local dictionary artifacts, not publication."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from .requirement_discovery import Record


class ReviewCheck(Record):
    review_id: str
    verdict: Literal["PASS", "FAIL"]
    notes: str = Field(min_length=1)


class ReviewFinding(Record):
    issue_id: str = Field(min_length=1)
    review_id: str
    description: str = Field(min_length=1)
    state: Literal["open", "resolved"]
    resolution: str | None = None
    resolved_in_revision: str | None = None


class FinalReview(Record):
    schema_version: Literal["dictionary_final_review_v1"] = "dictionary_final_review_v1"
    draft_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    previous_review_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    analysis_method: Literal["codex_self_review", "human_review"]
    reviewer_label: str = Field(min_length=1)
    checks: list[ReviewCheck]
    findings: list[ReviewFinding]
    summary: str = Field(min_length=1)


FINAL_REVIEW_INSTRUCTIONS = """최종 확인은 한국어로 작성한다.
초안의 모든 required_review_ids를 하나씩 확인하고 실제 원문과 비교해 PASS/FAIL 및 이유를 쓴다.
관찰: 소유 대상·원문 값·단위·비교연산자·필수/권장·개별/전체·장착/지원·조건 범위를 확인한다.
정의: 서로 다른 속성을 합쳤거나 같은 의미를 중복 생성하지 않았는지 정의와 매핑 원문을 비교한다.
유형·동의어: 대상의 종류와 원문 표현·적용 문맥을 확인한다.
coverage/logic: 비연속 구간·원자 조건 누락·이미지 미확인·AND/OR/IF를 확인한다.
자동 검사 통과를 의미 검토 대신 사용하지 않는다. 읽지 않은 범위를 PASS로 표시하지 않는다.
문제는 findings에 기록하고 수정본을 요구한다. 과거 지적사항을 삭제하지 않는다.
수정한 초안에 대해서만 resolved와 resolved_in_revision을 기록한다.
이 검토는 제안이며 자동 게시·운영 사전 변경을 수행하지 않는다.
"""


def validate_final_review(draft: dict, review: FinalReview, *, draft_sha256: str,
                          previous_review: FinalReview | None = None,
                          previous_review_sha256: str | None = None) -> dict:
    errors = list(draft["blocking_issues"])
    if not review.reviewer_label.strip() or not review.summary.strip():
        errors.append("missing_review_provenance")
    if review.draft_sha256 != draft_sha256 or review.source_bundle_sha256 != draft["source_bundle_sha256"]:
        errors.append("review_input_hash_mismatch")
    if review.previous_review_sha256 != previous_review_sha256:
        errors.append("previous_review_hash_mismatch")
    if bool(draft["parent_draft_sha256"]) != bool(previous_review):
        errors.append("parent_draft_requires_previous_review")
    if previous_review is not None and (previous_review.draft_sha256 != draft["parent_draft_sha256"]
                                      or previous_review.source_bundle_sha256 != draft["source_bundle_sha256"]):
        errors.append("previous_review_not_for_parent_draft")
    checks = {c.review_id: c for c in review.checks}
    required_ids = set(draft["required_review_ids"])
    if previous_review is not None:
        # A duplicate definition may be removed by a fix; its finding still needs
        # an explicit resolution rather than disappearing from the review.
        required_ids.update(f.review_id for f in previous_review.findings)
    if len(checks) != len(review.checks) or set(checks) != required_ids:
        errors.append("review_does_not_cover_required_items_exactly")
    for check in review.checks:
        if check.verdict != "PASS" or not check.notes.strip():
            errors.append(f"{check.review_id}:review_failed")
    findings = {f.issue_id: f for f in review.findings}
    if len(findings) != len(review.findings):
        errors.append("duplicate_review_issue")
    for finding in review.findings:
        if finding.review_id not in checks:
            errors.append(f"{finding.issue_id}:unknown_review_item")
        if finding.state == "open":
            errors.append(f"{finding.issue_id}:unresolved_finding")
        elif (not draft["parent_draft_sha256"] or not finding.resolution or not finding.resolution.strip()
              or finding.resolved_in_revision != draft["revision"]):
            errors.append(f"{finding.issue_id}:invalid_resolution")
    if previous_review is not None:
        for previous in previous_review.findings:
            current = findings.get(previous.issue_id)
            if current is None or current.review_id != previous.review_id:
                errors.append(f"{previous.issue_id}:previous_finding_dropped")
            elif current.state != "resolved":
                errors.append(f"{previous.issue_id}:previous_finding_not_resolved")
    return {"schema_version": "dictionary_final_check_v1", "draft_sha256": draft_sha256,
            "ready_for_offline_approval": not errors, "blocking_issues": sorted(set(errors)),
            "review_method": review.analysis_method,
            "independent_semantic_accuracy_measured": False,
            "published": False}


def approve_offline_dictionary(draft: dict, review: FinalReview, *, draft_sha256: str,
                               review_sha256: str, reviewer_label: str, authorization_note: str,
                               previous_review: FinalReview | None = None,
                               previous_review_sha256: str | None = None) -> dict:
    final_check = validate_final_review(draft, review, draft_sha256=draft_sha256,
                                        previous_review=previous_review,
                                        previous_review_sha256=previous_review_sha256)
    if not final_check["ready_for_offline_approval"] or not authorization_note.strip() or not reviewer_label.strip():
        raise ValueError("final review must pass and explicit local approval information is required")
    return {"schema_version": "bootstrap_dictionary_v1", "status": "offline_approved",
            "version": draft["revision"], "batch_id": draft["batch_id"],
            "approved_draft_sha256": final_check["draft_sha256"], "review_sha256": review_sha256,
            "base_dictionary_sha256": draft["base_dictionary_sha256"],
            "source_bundle_sha256": draft["source_bundle_sha256"],
            "source_notices": draft["source_notices"], "source_hashes": draft["source_hashes"],
            "catalogue": draft["catalogue"],
            "approval": {"reviewer_label": reviewer_label, "authorization_note": authorization_note,
                         "time_utc": datetime.now(timezone.utc).isoformat(),
                         "authority": "local_artifact_only_not_authenticated_admin_principal"},
            "published": False}
