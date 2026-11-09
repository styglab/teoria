"""Portable interpretation of a property value; never a Business Object definition."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from teoria.features.semantic_modeling.ontology.models import OntologyPublicationRef

InformationKind = Literal['requirement','declared_value','measurement','capability','reference','recommendation','option']


class SemanticObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    observation_id: str
    ontology: OntologyPublicationRef
    concept_id: UUID
    subject_refs: list[str] = Field(min_length=1)
    information_kind: InformationKind
    operator: Literal['eq','gte','lte','gt','lt','raw','one_of']
    scope: str = Field(min_length=1)
    value: dict[str, Any]
    value_raw: Any
    unit_raw: str | None = None
    source: dict[str, Any]
    conditions: list[Any] = Field(default_factory=list)
    effective_at: str | None = None
    observed_at: datetime | None = None

    @field_validator('effective_at')
    @classmethod
    def explicit_iso_time(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace('Z','+00:00'))
        return value
