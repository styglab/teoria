from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from teoria.intelligence.repository import SuggestionRepository
from teoria.intelligence.service import SuggestionApplicationError, SuggestionService
from teoria.metadata.openmetadata import OpenMetadataError
from teoria.admin.auth import AdminAuthorizer, AdminPrincipal


class EvidenceInput(BaseModel):
    evidence_type: str
    source_ref: str
    excerpt: str | None = None
    content_hash: str | None = None
    observed_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SuggestionInput(BaseModel):
    target_type: Literal["openmetadata_table", "openmetadata_column"]
    target_ref: str
    suggestion_type: Literal["description", "binding"]
    proposed_value: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None
    risk_level: Literal["low", "medium", "high"] = "low"
    model_provider: str
    model_name: str
    model_version: str | None = None
    policy_version: str
    evidence: list[EvidenceInput] = Field(default_factory=list)


class ReviewInput(BaseModel):
    decision: Literal["approve", "reject", "request_changes", "supersede"]
    comment: str | None = None


class BindingSuggestionInput(BaseModel):
    table_id: str
    column_name: str


def create_intelligence_router(
    repository: SuggestionRepository | None,
    service: SuggestionService | None,
    authorizer: AdminAuthorizer,
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/intelligence", tags=["intelligence"])

    def require_repository() -> SuggestionRepository:
        if repository is None:
            raise HTTPException(status_code=503, detail={"code": "app_database_unavailable"})
        return repository

    @router.get("/suggestions")
    def list_suggestions(status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> dict:
        return {"items": require_repository().list(status=status, limit=limit)}

    @router.post("/suggestions", status_code=201)
    def create_suggestion(
        payload: SuggestionInput,
        _principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ) -> dict:
        return require_repository().create(
            **payload.model_dump(mode="json", exclude={"evidence"}),
            evidence=[item.model_dump(mode="json") for item in payload.evidence],
        )

    @router.post("/binding-suggestions", status_code=201)
    async def create_binding_suggestion(
        payload: BindingSuggestionInput,
        _principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            return await service.suggest_column_binding(
                table_id=payload.table_id, column_name=payload.column_name,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "metadata_column_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "no_binding_candidate", "message": str(exc)}) from exc
        except SuggestionApplicationError as exc:
            raise HTTPException(status_code=503, detail={"code": "binding_suggestion_unavailable", "message": str(exc)}) from exc
        except OpenMetadataError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.get("/suggestions/{suggestion_id}")
    def get_suggestion(suggestion_id: UUID) -> dict:
        try:
            return require_repository().get(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc

    @router.post("/suggestions/{suggestion_id}/reviews")
    async def review_suggestion(
        suggestion_id: UUID,
        payload: ReviewInput,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_reviewer", "metadata_admin")),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            return await service.review_and_apply(
                suggestion_id, decision=payload.decision,
                reviewer=principal.actor, comment=payload.comment,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "invalid_suggestion_transition", "message": str(exc)}) from exc
        except SuggestionApplicationError as exc:
            raise HTTPException(status_code=502, detail={"code": "suggestion_application_failed", "message": str(exc)}) from exc

    return router
