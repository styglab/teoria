from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Provenance(BaseModel):
    source: str
    source_version: str | None = None
    observed_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SuggestionTarget(BaseModel):
    target_type: str
    target_ref: str
    target_version: str | None = None


class Suggestion(BaseModel):
    id: UUID
    target_type: str
    target_ref: str
    suggestion_type: str
    proposed_value: Any
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None
    risk_level: Literal["low", "medium", "high"]
    model_provider: str
    model_name: str
    model_version: str | None = None
    policy_version: str
    status: Literal["pending", "approved", "rejected", "changes_requested", "applied", "failed"] = "pending"
    created_at: datetime


class Evidence(BaseModel):
    id: UUID
    suggestion_id: UUID
    evidence_type: str
    source_ref: str
    excerpt: str | None = None
    content_hash: str | None = None
    observed_at: datetime
    provenance: dict[str, Any] = Field(default_factory=dict)


class Review(BaseModel):
    id: UUID
    suggestion_id: UUID
    decision: Literal["approve", "reject", "request_changes", "supersede"]
    reviewer: str
    comment: str | None = None
    reviewed_at: datetime
    resulting_change_ref: str | None = None
