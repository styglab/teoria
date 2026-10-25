from __future__ import annotations

from dataclasses import dataclass


from teoria.features.metadata_management.intelligence.asset_assessment.model_client import AssessmentError
from teoria.features.metadata_management.intelligence.asset_assessment.models import (
    AssessmentEvidence,
    AssessmentJob,
)
from teoria.features.metadata_management.intelligence.suggestions.binding_candidates import rank_binding_candidates


@dataclass
class AssessmentContext:
    model_input: dict
    columns: dict
    concepts: dict
    candidates_by_column: dict
    evidence: dict[str, AssessmentEvidence]


async def build_context(job: AssessmentJob, table: dict, bindings) -> AssessmentContext:
    selected = set(job["column_names"])
    columns = [
        c for c in table.get("columns", []) if not selected or c["name"] in selected
    ]
    if len(columns) > 30 or selected - {c["name"] for c in columns}:
        raise AssessmentError("assessment_columns_changed")
    # No row values, samples, or entire OpenMetadata documents go to the model or DB.
    context = {
        "scopes": job["scopes"],
        "assessment_date": str(job["assessment_date"]),
        "disclosure_context": job["disclosure_context"],
        "table": {
            "name": table["name"],
            "description": str(table.get("description") or "")[:4000],
            "columns": [
                {key: c.get(key) for key in ("name", "dataType", "description", "tags")}
                for c in columns
            ],
        },
        "evidence": {},
        "concepts": [],
    }
    evidence = {}
    column_map = {c["name"]: c for c in columns}
    table_ref = f"openmetadata://table/{table['fullyQualifiedName']}"
    evidence["table"] = {
        "evidence_type": "openmetadata_metadata",
        "source_ref": table_ref,
        "provenance": {"source_version": str(table["version"])},
    }
    for c in columns:
        evidence[f"column:{c['name']}"] = {
            "evidence_type": "openmetadata_metadata",
            "source_ref": f"openmetadata://column/{c['fullyQualifiedName']}",
            "provenance": {"source_version": str(table["version"])},
        }
    concepts = {}
    candidates_by_column = {}
    if "semantic_alignment" in job["scopes"]:
        if bindings is None:
            raise AssessmentError("ontology_reader_unavailable")
        published = await bindings.list_published_property_concepts()
        for c in columns:
            ranked = rank_binding_candidates(c, published, limit=3)
            candidates_by_column[c["name"]] = {item.concept_id for item in ranked}
            for item in ranked:
                concepts[item.concept_id] = next(
                    p for p in published if str(p["concept_id"]) == item.concept_id
                )
        context["concepts"] = list(concepts.values())
        context["candidates_by_column"] = {
            k: sorted(v) for k, v in candidates_by_column.items()
        }
        for identifier, concept in concepts.items():
            evidence[f"concept:{identifier}"] = {
                "evidence_type": "published_ontology",
                "source_ref": f"teoria://ontology/concept/{identifier}",
                "provenance": {
                    "stable_key": concept["stable_key"],
                    "version": concept["version"],
                },
            }
    return AssessmentContext(
        context, column_map, concepts, candidates_by_column, evidence
    )
