from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from teoria.metadata.models import MetadataStatus
from teoria.metadata.openmetadata import OpenMetadataError, OpenMetadataService


def create_metadata_router(service: OpenMetadataService | None) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/metadata", tags=["metadata"])

    def require_service() -> OpenMetadataService:
        if service is None:
            raise HTTPException(status_code=503, detail={"code": "openmetadata_disabled"})
        return service

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

    @router.get("/tables/{fully_qualified_name:path}")
    async def table(fully_qualified_name: str) -> dict:
        return await _call(require_service().get_table(fully_qualified_name))

    return router


async def _call(awaitable):
    try:
        result = await awaitable
    except OpenMetadataError as exc:
        status_code = 404 if exc.status_code == 404 else 503
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result
