from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from teoria.admin.auth import AdminAuthorizer, AdminPrincipal

from teoria.metadata.models import MetadataStatus
from teoria.metadata.openmetadata import OpenMetadataError, OpenMetadataService


def create_metadata_router(service: OpenMetadataService | None, authorizer: AdminAuthorizer,
                           context_service=None, *, public_read: bool = False) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/metadata", tags=["metadata"],
                       dependencies=[] if public_read else [Depends(authorizer.require())])

    def require_service() -> OpenMetadataService:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "openmetadata_disabled"})
        return service

    @router.get("/asset-context/{table_id}")
    async def asset_context(table_id: UUID, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        if context_service is None:
            raise HTTPException(status_code=503, detail={"code": "asset_context_unavailable"})
        return await _call(context_service.get(str(table_id)))

    @router.get("/status")
    async def status() -> dict:
        if service is None:
            return MetadataStatus(enabled=False, available=False, reason="openmetadata_disabled").model_dump()
        try:
            return (await service.status()).model_dump()
        except OpenMetadataError as exc:
            return MetadataStatus(
                enabled=True,
                available=False,
                base_url=service.base_url,
                database_service=service.database_service,
                reason=exc.code,
            ).model_dump()

    @router.get("/services")
    async def services(limit: int = Query(50, ge=1, le=100), after: str | None = None) -> dict:
        return await _call(require_service().list_services(limit=limit, after=after))

    @router.get("/databases")
    async def databases(service_name: str | None = None, limit: int = Query(50, ge=1, le=100), after: str | None = None) -> dict:
        resolved = require_service()
        return await _call(resolved.list_databases(service=service_name or resolved.database_service, limit=limit, after=after))

    @router.get("/schemas")
    async def schemas(database: str | None = None, limit: int = Query(50, ge=1, le=100), after: str | None = None) -> dict:
        return await _call(require_service().list_schemas(database=database, limit=limit, after=after))

    @router.get("/tables")
    async def tables(database_schema: str | None = None, limit: int = Query(50, ge=1, le=100), after: str | None = None) -> dict:
        return await _call(require_service().list_tables(database_schema=database_schema, limit=limit, after=after))

    @router.get("/tables/{table_id}/lineage")
    async def lineage(table_id: str, upstream_depth: int = Query(1, ge=0, le=3), downstream_depth: int = Query(1, ge=0, le=3)) -> dict:
        return await _call(require_service().get_table_lineage(table_id, upstream_depth=upstream_depth, downstream_depth=downstream_depth))

    @router.get("/tables/{table_id}/sample-data")
    async def samples(table_id: str, response: Response, limit: int = Query(10, ge=1, le=50), include_values: bool = False,
                      principal: AdminPrincipal = Depends(authorizer.require())) -> dict:
        response.headers["Cache-Control"] = "no-store"
        if include_values and "metadata_sample_reader" not in principal.roles:
            raise HTTPException(status_code=403, detail={"code": "metadata_sample_reader_required",
                                                        "message": "샘플 값을 조회할 권한이 없습니다."})
        return await _call(require_service().get_table_samples(table_id, limit=limit, include_values=include_values))

    @router.get("/tables/{table_id}/profile")
    async def profile(table_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return await _call(require_service().get_table_profile(table_id))

    @router.get("/tables/{fully_qualified_name:path}")
    async def table(fully_qualified_name: str) -> dict:
        return await _call(require_service().get_table(fully_qualified_name))

    return router


async def _call(awaitable):
    try:
        result = await awaitable
    except OpenMetadataError as exc:
        status_code = exc.status_code if exc.status_code in {403, 404} else 503
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result
