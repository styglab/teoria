from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.metadata_management.intelligence.asset_assessment.models import (
    AssessmentPage,
    AssessmentRequest,
    AssessmentResponse,
)
from teoria.features.metadata_management.catalog.models import MetadataTargetRef
from teoria.integrations.openmetadata import OpenMetadataError


def create_asset_assessment_router(
    repository,
    metadata_client,
    authorizer: AdminAuthorizer,
    *,
    enabled: bool,
    model_name: str | None,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/admin/intelligence/asset-assessments", tags=["asset-assessments"]
    )

    def require_repository():
        if repository is None:
            raise HTTPException(503, detail={"code": "app_database_unavailable"})
        return repository

    @(
        router.post(
            "",
            status_code=202,
            response_model=AssessmentResponse,
            response_model_exclude_unset=True,
        )
    )
    async def create(
        payload: AssessmentRequest,
        response: Response,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        response.headers["Cache-Control"] = "no-store"
        if not enabled or not model_name or metadata_client is None:
            raise HTTPException(503, detail={"code": "asset_assessment_not_configured"})
        require_repository()
        try:
            table = await metadata_client.get_table_by_name(payload.table_fqn)
        except OpenMetadataError as exc:
            raise HTTPException(
                exc.status_code if exc.status_code in {403, 404} else 503,
                detail={"code": exc.code},
            ) from None
        if (
            table.get("fullyQualifiedName") != payload.table_fqn
            or not table.get("id")
            or table.get("version") is None
        ):
            raise HTTPException(503, detail={"code": "asset_identity_unavailable"})
        names = {column["name"] for column in table.get("columns", [])}
        if set(payload.column_names) - names:
            raise HTTPException(422, detail={"code": "assessment_column_not_found"})
        if not payload.column_names and len(names) > 30:
            raise HTTPException(422, detail={"code": "select_up_to_30_columns"})
        target = MetadataTargetRef(
            entity_id=str(table["id"]),
            entity_type="table",
            fully_qualified_name=table["fullyQualifiedName"],
            version=table["version"],
        )
        return await require_repository().create(
            target_ref=target.model_dump(),
            request=payload,
            actor=principal.actor,
            model=model_name,
        )

    @router.get("", response_model=AssessmentPage, response_model_exclude_unset=True)
    async def list_assessments(
        response: Response,
        table_id: UUID,
        limit: int = Query(10, ge=1, le=50),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        response.headers["Cache-Control"] = "no-store"
        return {"items": await require_repository().list(table_id, limit=limit)}

    @router.get(
        "/{assessment_id}",
        response_model=AssessmentResponse,
        response_model_exclude_unset=True,
    )
    async def get(
        assessment_id: UUID,
        response: Response,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        response.headers["Cache-Control"] = "no-store"
        try:
            return await require_repository().get(assessment_id)
        except KeyError:
            raise HTTPException(
                404, detail={"code": "asset_assessment_not_found"}
            ) from None

    return router
