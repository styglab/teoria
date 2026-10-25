from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


OntologyStatus = Literal["draft", "in_review", "approved", "published", "deprecated"]
BusinessObjectId = Annotated[UUID, Field(description="Stable Business Object identifier")]
OntologyPropertyId = Annotated[UUID, Field(description="Stable Ontology Property identifier")]


class OntologyVersion(BaseModel):
    id: UUID
    ontology_id: UUID
    version: str
    status: OntologyStatus
    based_on_version_id: UUID | None = None


class BusinessObject(BaseModel):
    id: BusinessObjectId
    ontology_version_id: UUID
    namespace: str
    code: str
    name: str
    description: str
    identity_policy: dict[str, Any] = Field(default_factory=dict)
    status: OntologyStatus = "draft"


class OntologyProperty(BaseModel):
    id: OntologyPropertyId
    business_object_id: BusinessObjectId
    code: str
    name: str
    description: str
    value_type: str
    cardinality: Literal["one", "optional", "many"] = "optional"
    unit: str | None = None
    temporal: bool = False
    status: OntologyStatus = "draft"


class Relationship(BaseModel):
    id: UUID
    ontology_version_id: UUID
    code: str
    name: str
    source_object_id: UUID
    target_object_id: UUID
    source_cardinality: str = "many"
    target_cardinality: str = "many"
    inverse_relationship_id: UUID | None = None
    temporal: bool = False
    transitive: bool = False
    status: OntologyStatus = "draft"


class BusinessRule(BaseModel):
    id: UUID
    ontology_version_id: UUID
    code: str
    name: str
    description: str
    subject_object_id: UUID
    expression_language: str
    expression: dict[str, Any]
    evaluator_key: str | None = None
    version: str
    effective_from: date | None = None
    effective_to: date | None = None
    status: OntologyStatus = "draft"


class Metric(BaseModel):
    id: UUID
    ontology_version_id: UUID
    code: str
    name: str
    description: str
    subject_object_id: UUID
    formula: dict[str, Any]
    aggregation: str
    grain: list[str]
    dimensions: list[str] = Field(default_factory=list)
    unit: str | None = None
    time_basis: str | None = None
    version: str
    status: OntologyStatus = "draft"
