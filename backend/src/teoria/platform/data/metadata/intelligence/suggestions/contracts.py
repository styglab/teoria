from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceInput(BaseModel):
    evidence_type: str
    source_ref: str
    excerpt: str | None = None
    content_hash: str | None = None
    observed_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SuggestionInput(BaseModel):
    target_type: Literal[
        "openmetadata_table",
        "openmetadata_column",
        "openmetadata_glossary",
        "ontology",
    ]
    target_ref: str
    suggestion_type: Literal[
        "description",
        "binding",
        "glossary_term",
        "glossary_term_assignment",
        "ontology_change",
        "test_suite",
        "quality_test",
    ]
    proposed_value: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None
    risk_level: Literal["low", "medium", "high"] = "low"
    model_provider: str
    model_name: str
    model_version: str | None = None
    policy_version: str
    evidence: list[EvidenceInput] = Field(default_factory=list)


def metadata_proposal_bundle_schema() -> dict:
    """Export the Skill subset of the Admin Suggestion contract.

    The Skill keeps this generated schema as a portable reference. Worker generation
    validates against SuggestionInput; Skill-only restrictions do not narrow the API.
    """
    suggestion = SuggestionInput.model_json_schema()
    definitions = suggestion.pop("$defs")
    suggestion["title"] = "Metadata proposal"
    suggestion["additionalProperties"] = False
    suggestion["required"] = [
        "target_type",
        "target_ref",
        "suggestion_type",
        "proposed_value",
        "confidence",
        "risk_level",
        "model_provider",
        "model_name",
        "policy_version",
        "evidence",
    ]
    properties = suggestion["properties"]
    properties["suggestion_type"]["enum"] = [
        "description",
        "binding",
        "glossary_term",
        "glossary_term_assignment",
    ]
    properties["policy_version"] = {"const": "metadata-asset-analysis-v1"}
    properties["evidence"]["minItems"] = 1
    for key in ("model_provider", "model_name"):
        properties[key]["minLength"] = 1
    properties["warnings"] = {"type": "array", "items": {"type": "string"}}
    suggestion["allOf"] = [
        {
            "if": {"properties": {"target_type": {"const": target}}},
            "then": {"properties": {"target_ref": {"pattern": "^" + prefix + ".+"}}},
        }
        for target, prefix in (
            ("openmetadata_table", "openmetadata://table/"),
            ("openmetadata_column", "openmetadata://column/"),
            ("openmetadata_glossary", "openmetadata://glossary/"),
            ("ontology", "teoria://ontology/"),
        )
    ]
    suggestion["allOf"].append(
        {
            "if": {
                "properties": {
                    "suggestion_type": {"const": "description"},
                    "target_type": {"const": "openmetadata_column"},
                }
            },
            "then": {
                "properties": {
                    "proposed_value": {
                        "required": [
                            "description",
                            "table_id",
                            "column_name",
                            "column_fqn",
                            "source_version",
                            "source_description",
                        ]
                    }
                }
            },
        }
    )
    evidence = definitions["EvidenceInput"]
    evidence["additionalProperties"] = False
    for key in ("evidence_type", "source_ref"):
        evidence["properties"][key]["minLength"] = 1
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": definitions,
        "title": "Teoria metadata proposal bundle",
        "type": "object",
        "additionalProperties": False,
        "required": ["bundle_version", "suggestions"],
        "properties": {
            "bundle_version": {"const": "1.0"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "suggestions": {"type": "array", "minItems": 1, "items": suggestion},
        },
    }
