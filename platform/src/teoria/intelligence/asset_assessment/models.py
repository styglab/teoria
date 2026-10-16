from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, NamedTuple, NotRequired, TypedDict
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from teoria.intelligence.suggestions.contracts import EvidenceInput
from teoria.metadata.models import MetadataTargetRef

Scope = Literal["metadata_enrichment", "semantic_alignment", "disclosure_assessment"]

AssessmentStatus = Literal["queued", "running", "completed", "partial", "failed"]
DisclosureContext = Literal["public_release", "restricted_sharing"]


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_fqn: str = Field(min_length=1, max_length=1000)
    scopes: list[Scope] = Field(min_length=1, max_length=3)
    column_names: list[str] = Field(default_factory=list, max_length=30)
    assessment_date: date = Field(
        default_factory=lambda: datetime.now(ZoneInfo("Asia/Seoul")).date()
    )
    disclosure_context: DisclosureContext = "public_release"

    @field_validator("scopes", "column_names")
    @classmethod
    def normalize_selection(cls, value):
        return sorted(set(value))


class ChangeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["description", "binding"]
    column_name: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    concept_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope
    column_name: str | None = None
    summary: str = Field(min_length=1, max_length=2000)
    information_type: str | None = Field(default=None, max_length=100)
    internal_processing: Literal[
        "review_required", "basis_identified", "not_assessed"
    ] = "not_assessed"
    disclosure_recommendation: Literal[
        "review_required", "withhold_raw", "transform_and_reassess", "candidate"
    ] = "review_required"
    protection_recommendation: str | None = Field(default=None, max_length=1000)
    tag_candidates: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class AssessmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[ChangeCandidate] = Field(default_factory=list, max_length=60)
    findings: list[Finding] = Field(default_factory=list, max_length=60)


class LawQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("queries")
    @classmethod
    def bounded_queries(cls, values):
        if any(
            not 2 <= len(value) <= 100 or len(value.split()) > 8 for value in values
        ):
            raise ValueError("Invalid law query")
        return values


class AssessmentTarget(TypedDict):
    entity_id: str
    fully_qualified_name: str
    version: float
    system: NotRequired[Literal["openmetadata"]]
    entity_type: NotRequired[str]


class AssessmentJob(TypedDict):
    """Internal claimed work; claim_token is never an API response field."""

    assessment_id: UUID
    claim_token: UUID
    target_ref: AssessmentTarget
    scopes: list[Scope]
    column_names: list[str]
    assessment_date: date | str
    disclosure_context: DisclosureContext
    requested_by: str
    model_name: str


class AssessmentEvidence(TypedDict):
    evidence_type: str
    source_ref: str
    provenance: dict[str, Any]
    content_hash: NotRequired[str]


class AssessmentAnalysis(NamedTuple):
    proposals: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    partial: bool


class AssessmentFindingResponse(BaseModel):
    """Validated findings and server diagnostics, distinct from model candidates."""

    model_config = ConfigDict(extra="forbid")
    summary: str
    scope: Scope | None = None
    column_name: str | None = None
    code: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceInput] = Field(default_factory=list)
    information_type: str | None = None
    internal_processing: (
        Literal["review_required", "basis_identified", "not_assessed"] | None
    ) = None
    disclosure_recommendation: (
        Literal[
            "review_required", "withhold_raw", "transform_and_reassess", "candidate"
        ]
        | None
    ) = None
    protection_recommendation: str | None = None
    tag_candidates: list[str] = Field(default_factory=list)
    legal_applicability_confirmed: bool | None = None
    tag_candidates_verified: bool | None = None
    invalid_evidence_count: int | None = None
    unknown_column: bool | None = None
    unknown_scope: bool | None = None


class AssessmentResponse(BaseModel):
    """Public allowlist; execution claim and request deduplication keys stay internal."""

    assessment_id: UUID
    target_ref: MetadataTargetRef
    scopes: list[Scope]
    column_names: list[str]
    assessment_date: date
    disclosure_context: DisclosureContext
    requested_by: str
    status: AssessmentStatus
    model_name: str
    policy_version: str
    attempts: int
    lease_until: datetime | None
    error_code: str | None
    findings: list[AssessmentFindingResponse]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    suggestion_ids: list[UUID]


class AssessmentPage(BaseModel):
    items: list[AssessmentResponse]
