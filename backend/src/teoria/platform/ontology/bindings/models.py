from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MetadataTargetRef(BaseModel):
    target_type: Literal["glossary_term", "data_asset"]
    system: Literal["openmetadata"] = "openmetadata"
    entity_id: str
    entity_type: str
    fully_qualified_name: str
    version: str | None = None


class ApiFieldTargetRef(BaseModel):
    target_type: Literal["api_field"] = "api_field"
    system: Literal["provider"] = "provider"
    source_id: str
    operation_id: str
    object_id: str
    field_path: str
    contract_version: str | None = None


class CapabilityTargetRef(BaseModel):
    target_type: Literal["capability", "capability_input", "capability_output"]
    system: Literal["teoria"] = "teoria"
    capability_id: str
    field_path: str | None = None
    contract_version: str | None = None


BindingTarget = Annotated[
    MetadataTargetRef | ApiFieldTargetRef | CapabilityTargetRef,
    Field(discriminator="target_type"),
]


class OntologyBinding(BaseModel):
    id: UUID
    ontology_ref_type: Literal["object", "property", "relationship", "rule", "metric"]
    ontology_ref_id: UUID
    ontology_concept_id: UUID | None = None
    target: BindingTarget
    binding_type: str
    purpose: str | None = None
    authority: Literal["authoritative", "preferred", "supplemental"] = "supplemental"
    priority: int = 100
    condition: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["draft", "approved", "rejected", "deprecated"] = "draft"
    valid_from: date | None = None
    valid_to: date | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    approved_by: str | None = None
