from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

Scope = Literal['metadata_enrichment', 'semantic_alignment', 'disclosure_assessment']


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    table_fqn: str = Field(min_length=1, max_length=1000)
    scopes: list[Scope] = Field(min_length=1, max_length=3)
    column_names: list[str] = Field(default_factory=list, max_length=30)
    assessment_date: date = Field(default_factory=lambda: datetime.now(ZoneInfo('Asia/Seoul')).date())
    disclosure_context: Literal['public_release', 'restricted_sharing'] = 'public_release'

    @field_validator('scopes', 'column_names')
    @classmethod
    def normalize_selection(cls, value):
        return sorted(set(value))


class ChangeCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['description', 'binding']
    column_name: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    concept_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class Finding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: Scope
    column_name: str | None = None
    summary: str = Field(min_length=1, max_length=2000)
    information_type: str | None = Field(default=None, max_length=100)
    internal_processing: Literal['review_required', 'basis_identified', 'not_assessed'] = 'not_assessed'
    disclosure_recommendation: Literal['review_required', 'withhold_raw', 'transform_and_reassess', 'candidate'] = 'review_required'
    protection_recommendation: str | None = Field(default=None, max_length=1000)
    tag_candidates: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: list[ChangeCandidate] = Field(default_factory=list, max_length=60)
    findings: list[Finding] = Field(default_factory=list, max_length=60)


class LawQueries(BaseModel):
    model_config = ConfigDict(extra='forbid')
    queries: list[str] = Field(default_factory=list, max_length=3)

    @field_validator('queries')
    @classmethod
    def bounded_queries(cls, values):
        if any(not 2 <= len(value) <= 100 or len(value.split()) > 8 for value in values):
            raise ValueError('Invalid law query')
        return values
