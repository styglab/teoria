from __future__ import annotations

import json
from uuid import UUID


from teoria.features.metadata_management.intelligence.asset_assessment.model_client import AssessmentError
from teoria.features.metadata_management.intelligence.asset_assessment.models import (
    AssessmentJob,
    AssessmentOutput,
    AssessmentTarget,
)
from teoria.features.metadata_management.intelligence.asset_assessment.proposals import build_proposal


def verify_table(table: dict, target: AssessmentTarget) -> None:
    if (
        str(table.get("id")) != target["entity_id"]
        or table.get("fullyQualifiedName") != target["fully_qualified_name"]
        or table.get("version") != target["version"]
    ):
        raise AssessmentError("stale_evidence")


def require_bounded_context(context: dict) -> None:
    if len(json.dumps(context, ensure_ascii=False, default=str)) > 100_000:
        raise AssessmentError("assessment_context_too_large")


async def validate_output(
    job: AssessmentJob,
    table: dict,
    columns: dict,
    concepts: dict,
    candidates_by_column: dict,
    evidence: dict,
    output: AssessmentOutput,
    bindings,
) -> tuple[list[dict], list[dict], bool]:
    proposals, findings, seen = [], [], set()
    rejected = False
    for change in output.changes:
        key = (change.kind, change.column_name)
        source_id = f"column:{change.column_name}" if change.column_name else "table"
        required = {source_id}
        concept = concepts.get(change.concept_id)
        scope = (
            "metadata_enrichment"
            if change.kind == "description"
            else "semantic_alignment"
        )
        if change.kind == "binding":
            required.add(f"concept:{change.concept_id}")
        valid = (
            scope in job["scopes"]
            and key not in seen
            and (change.column_name is None or change.column_name in columns)
            and required.issubset(change.evidence_ids)
            and set(change.evidence_ids).issubset(evidence)
        )
        if change.kind == "binding":
            valid = (
                valid
                and concept is not None
                and change.concept_id
                in candidates_by_column.get(change.column_name, set())
            )
        if change.kind == "description":
            valid = valid and bool(change.description and change.description.strip())
        if not valid:
            rejected = True
            continue
        seen.add(key)
        column = columns.get(change.column_name)
        fqn = column["fullyQualifiedName"] if column else table["fullyQualifiedName"]
        current = column.get("description") if column else table.get("description")
        if (
            change.kind == "description"
            and change.description.strip() == (current or "").strip()
        ):
            continue
        if change.kind == "binding":
            existing = await bindings.get_active_binding(
                ontology_concept_id=UUID(change.concept_id),
                target_type="data_asset",
                target_locator=fqn,
            )
            if existing:
                continue
        proposals.append(build_proposal(change, job, table, column, concept, evidence))
    for finding in output.findings:
        if (
            finding.scope not in job["scopes"]
            or finding.column_name is not None
            and finding.column_name not in columns
            or not set(finding.evidence_ids).issubset(evidence)
        ):
            rejected = True
            findings.append(
                {
                    "summary": "진단 결과의 범위·대상·근거 식별자가 입력과 일치하지 않아 제외했습니다.",
                    "code": "finding_reference_invalid",
                    "invalid_evidence_count": len(
                        set(finding.evidence_ids) - evidence.keys()
                    ),
                    "unknown_column": finding.column_name is not None
                    and finding.column_name not in columns,
                    "unknown_scope": finding.scope not in job["scopes"],
                }
            )
            continue
        item = finding.model_dump()
        item["evidence"] = [evidence[k] for k in finding.evidence_ids]
        if finding.scope == "disclosure_assessment":
            item["legal_applicability_confirmed"] = False
            item["tag_candidates_verified"] = False
            # Approval / legal basis must never be inferred from the model's own confidence.
            item["internal_processing"] = "review_required"
            if not any(k.startswith("law:") for k in finding.evidence_ids):
                item["disclosure_recommendation"] = "review_required"
                item["protection_recommendation"] = None
                item["tag_candidates"] = []
                item["summary"] = "법령 근거가 확인되지 않았습니다. " + item["summary"]
                rejected = True
        findings.append(item)
    if rejected:
        findings.append(
            {
                "summary": "일부 모델 결과는 대상·근거·분석 범위 검증을 통과하지 못해 제외했습니다.",
                "code": "invalid_candidates_excluded",
            }
        )
    return proposals, findings, rejected
