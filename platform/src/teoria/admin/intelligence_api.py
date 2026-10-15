from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from teoria.intelligence.repository import SuggestionRepository
from teoria.intelligence.service import SuggestionApplicationError, SuggestionService
from teoria.metadata.openmetadata import OpenMetadataError
from teoria.metadata.openmetadata.mapper import table_detail
from teoria.metadata.asset_context import asset_targets, suggestion_target_refs
from teoria.intelligence.application import ApplicationStateError
from teoria.admin.auth import AdminAuthorizer, AdminPrincipal


class EvidenceInput(BaseModel):
    evidence_type: str
    source_ref: str
    excerpt: str | None = None
    content_hash: str | None = None
    observed_at: datetime | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SuggestionInput(BaseModel):
    target_type: Literal[
        "openmetadata_table", "openmetadata_column", "openmetadata_glossary",
        "ontology",
    ]
    target_ref: str
    suggestion_type: Literal[
        "description", "binding", "glossary_term", "glossary_term_assignment",
        "ontology_change", "test_suite", "quality_test",
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


class ReviewInput(BaseModel):
    decision: Literal["approve", "reject", "request_changes", "supersede"]
    comment: str | None = None


class BindingSuggestionInput(BaseModel):
    table_id: str
    column_name: str


class DescriptionSuggestionInput(BaseModel):
    table_id: str
    description: str = Field(min_length=1, max_length=10000)
    column_name: str | None = None


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
    async def list_suggestions(
        response: Response,
        status: Literal["pending", "approved", "rejected", "changes_requested", "applied", "failed"] | None = None,
        limit: int = Query(50, ge=1, le=100),
        after: str | None = Query(None, max_length=512),
        table_id: UUID | None = None,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        repo = require_repository()
        refs = None
        if table_id is not None:
            if service is None or service.metadata_client is None:
                raise HTTPException(status_code=503, detail={"code": "openmetadata_disabled"})
            try:
                document = await service.metadata_client.get(
                    f"v1/tables/{table_id}", params={"fields": "columns,tags"},
                )
                if str(document.get("id", "")).lower() != str(table_id):
                    raise OpenMetadataError("openmetadata_invalid_response", "Table identity does not match")
                refs = suggestion_target_refs(str(table_id), *asset_targets(document))
            except OpenMetadataError as exc:
                raise HTTPException(status_code=exc.status_code if exc.status_code in {403, 404} else 503,
                                    detail={"code": exc.code, "message": str(exc)}) from exc
            except KeyError as exc:
                raise HTTPException(status_code=503, detail={"code": "openmetadata_invalid_response"}) from exc
        try:
            return repo.list_page(status=status, limit=limit, after=after, target_refs=refs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_suggestion_cursor", "message": str(exc)}) from exc

    @router.post("/suggestions", status_code=201)
    def create_suggestion(
        payload: SuggestionInput,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ) -> dict:
        return require_repository().create(
            **payload.model_dump(mode="json", exclude={"evidence"}),
            submitted_by=principal.actor,
            evidence=[item.model_dump(mode="json") for item in payload.evidence],
        )

    @router.post("/binding-suggestions", status_code=201)
    async def create_binding_suggestion(
        payload: BindingSuggestionInput,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            return await service.suggest_column_binding(
                table_id=payload.table_id, column_name=payload.column_name,
                submitted_by=principal.actor,
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

    @router.post("/description-suggestions", status_code=201)
    async def create_description_suggestion(
        payload: DescriptionSuggestionInput,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ) -> dict:
        if service is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "intelligence_service_unavailable"},
            )
        try:
            return await service.suggest_description_change(
                table_id=payload.table_id,
                column_name=payload.column_name,
                description=payload.description,
                submitted_by=principal.actor,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail={"code": "metadata_column_not_found"}
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_description_change", "message": str(exc)},
            ) from exc
        except (SuggestionApplicationError, OpenMetadataError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": getattr(exc, "code", "description_suggestion_unavailable"),
                    "message": str(exc),
                },
            ) from exc

    @router.get("/suggestions/{suggestion_id}")
    def get_suggestion(
        suggestion_id: UUID, response: Response,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            return require_repository().get(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc

    @router.post("/suggestions/{suggestion_id}/reviews")
    async def review_suggestion(
        suggestion_id: UUID,
        payload: ReviewInput,
        principal: AdminPrincipal = Depends(authorizer.require(
            "metadata_reviewer", "metadata_admin", "ontology_owner",
        )),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            suggestion = require_repository().get(suggestion_id)
            if (
                suggestion.get("suggestion_type") == "ontology_change"
                and "ontology_owner" not in principal.roles
            ):
                raise HTTPException(
                    status_code=403,
                    detail={"code": "admin_role_required", "required_roles": ["ontology_owner"]},
                )
            return await service.review_and_apply(
                suggestion_id, decision=payload.decision,
                reviewer=principal.actor, comment=payload.comment,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "invalid_suggestion_transition", "message": str(exc)}) from exc
        except SuggestionApplicationError as exc:
            status_code = 409 if exc.code == "stale_evidence" else 502
            raise HTTPException(
                status_code=status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @router.post("/suggestions/{suggestion_id}/applications/reconcile")
    async def reconcile_application(
        suggestion_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_reviewer", "metadata_admin", "ontology_owner")),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            suggestion = require_repository().get(suggestion_id)
            if suggestion.get("suggestion_type") == "ontology_change" and "ontology_owner" not in principal.roles:
                raise HTTPException(status_code=403, detail={"code": "admin_role_required", "required_roles": ["ontology_owner"]})
            return await service.reconcile_application(suggestion_id, actor=principal.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        except (SuggestionApplicationError, ApplicationStateError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "application_reconciliation_failed"), "message": str(exc)}) from exc
        except OpenMetadataError as exc:
            raise HTTPException(status_code=502, detail={"code": exc.code, "message": str(exc)}) from exc

    @router.get("/suggestions/{suggestion_id}/applications/attempts")
    def application_attempts(
        suggestion_id: UUID, response: Response,
        limit: int = Query(50, ge=1, le=100), after: UUID | None = None,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            return require_repository().application_attempts(suggestion_id, limit=limit, after=after)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_application_history_cursor"}) from exc

    @router.get("/suggestions/{suggestion_id}/target")
    async def suggestion_target(
        suggestion_id: UUID, response: Response,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            suggestion = require_repository().get(suggestion_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        proposed = suggestion["proposed_value"]
        try:
            table_id = UUID(str(proposed.get("table_id", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "suggestion_table_reference_unavailable"}) from exc
        if service is None or service.metadata_client is None:
            raise HTTPException(status_code=503, detail={"code": "openmetadata_disabled"})
        try:
            document = await service.metadata_client.get(
                f"v1/tables/{table_id}", params={"fields": "columns,tags"},
            )
            if str(document.get("id", "")).lower() != str(table_id):
                raise OpenMetadataError("openmetadata_invalid_response", "Table identity does not match")
            return table_detail(document).model_dump(mode="json")
        except OpenMetadataError as exc:
            raise HTTPException(status_code=exc.status_code if exc.status_code in {403, 404} else 503,
                                detail={"code": exc.code, "message": str(exc)}) from exc

    @router.post("/suggestions/{suggestion_id}/applications/retry")
    async def retry_application(
        suggestion_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_reviewer", "metadata_admin", "ontology_owner")),
    ) -> dict:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "intelligence_service_unavailable"})
        try:
            suggestion = require_repository().get(suggestion_id)
            if suggestion.get("suggestion_type") == "ontology_change" and "ontology_owner" not in principal.roles:
                raise HTTPException(status_code=403, detail={"code": "admin_role_required", "required_roles": ["ontology_owner"]})
            if suggestion["status"] not in {"approved", "failed"}:
                raise ValueError("Only previously approved applications can be retried")
            # Reuse evidence validation and the fenced application claim; never approve here.
            return await service.review_and_apply(
                suggestion_id, decision="approve", reviewer=principal.actor, comment=None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "suggestion_not_found"}) from exc
        except (SuggestionApplicationError, ApplicationStateError, ValueError) as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "application_retry_failed"), "message": str(exc)}) from exc

    return router
