"""Explicit approval of fixed versions and authenticated version discovery."""

from uuid import UUID

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from teoria.platform.access_control.auth import AdminPrincipal
from teoria.domains.goods.data_processing.storage.artifact_reader import (
    ArtifactReadError,
)
from teoria.domains.goods.normalization.processing_criteria_service import (
    ApplicationStandardInput,
)


def create_application_standards_router(service, authorizer):
    router = APIRouter(
        prefix="/v1/admin/specification-processing/application-standards",
        tags=["specification-processing"],
    )

    def require_service():
        if service is None:
            raise HTTPException(
                503, detail={"code": "application_standards_unavailable"}
            )
        return service

    async def translate(call):
        try:
            return await call
        except ArtifactReadError as exc:
            raise HTTPException(exc.status_code, exc.detail) from None
        except KeyError:
            raise HTTPException(
                404, detail={"code": "application_standard_not_found"}
            ) from None
        except (ValueError, psycopg.IntegrityError) as exc:
            if str(exc) == "standard_has_no_application_rules":
                raise HTTPException(
                    409,
                    detail={
                        "code": "standard_has_no_application_rules",
                        "message": "적용할 규칙이 없는 표준은 승인하거나 실행할 수 없습니다. 표준·프로파일을 먼저 작성하고 검토하세요.",
                    },
                ) from None
            raise HTTPException(
                409,
                detail={"code": "application_standard_conflict", "message": str(exc)},
            ) from None
        except (httpx.HTTPError, OSError):
            raise HTTPException(
                503, detail={"code": "artifact_storage_unavailable"}
            ) from None

    @router.get("")
    async def list_versions(
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
        actor: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await translate(require_service().repository.list(offset, limit))

    @router.get("/sources")
    async def sources(
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
        actor: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(require_service().sources(offset, limit))

    @router.post("", status_code=201)
    async def approve(
        payload: ApplicationStandardInput,
        actor: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(require_service().create(payload, actor=actor.actor))

    @router.get("/sources/{run_id}")
    async def source_readiness(
        run_id: str,
        actor: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(require_service().readiness(run_id))

    @router.get("/{release_id}")
    async def get_version(
        release_id: UUID,
        actor: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await translate(require_service().repository.get(release_id))

    return router
