from __future__ import annotations

from teoria.features.metadata_management.intelligence.asset_assessment.models import AssessmentJob
from teoria.features.metadata_management.intelligence.suggestions.contracts import SuggestionInput


def build_proposal(
    change,
    job: AssessmentJob,
    table: dict,
    column: dict | None,
    concept: dict | None,
    evidence: dict,
) -> dict:
    """Convert a validated candidate into a pending Suggestion payload."""
    fqn = column["fullyQualifiedName"] if column else table["fullyQualifiedName"]
    current = column.get("description") if column else table.get("description")
    proposed = {"table_id": str(table["id"]), "source_version": str(table["version"])}
    if change.kind == "description":
        proposed.update(
            description=change.description.strip(), source_description=current
        )
        proposed.update(
            {"column_name": column["name"], "column_fqn": fqn}
            if column
            else {"fully_qualified_name": fqn}
        )
    else:
        proposed.update(
            ontology_concept_id=change.concept_id,
            ontology_ref_type=concept["concept_kind"],
            ontology_stable_key=concept["stable_key"],
            external_entity_id=fqn,
            entity_type="column",
            fully_qualified_name=fqn,
            external_version=str(table["version"]),
            binding_type="represents",
        )
    proposal = {
        "target_type": "openmetadata_column" if column else "openmetadata_table",
        "target_ref": f"openmetadata://{'column' if column else 'table'}/{fqn}",
        "suggestion_type": change.kind,
        "proposed_value": proposed,
        "confidence": min(change.confidence, 0.69),
        "risk_level": "medium",
        "rationale": change.reason
        + "\n주의: 메타데이터와 기존 개념에 기초한 추정입니다. 원천 업무 문서 대조가 필요합니다.",
        "model_provider": "configured_gateway",
        "model_name": job["model_name"],
        "model_version": None,
        "policy_version": "asset_assessment_v1",
        "submitted_by": job["requested_by"],
        "evidence": [evidence[k] for k in change.evidence_ids],
    }

    SuggestionInput.model_validate(proposal)
    return proposal
