from __future__ import annotations

from fastapi import APIRouter, HTTPException

from teoria.binding.repository import BindingRepository


def create_property_context_router(repository: BindingRepository | None) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/semantic", tags=["semantic"])

    @router.get("/properties/{namespace}/{object_code}/{property_code}")
    async def property_context(
        namespace: str, object_code: str, property_code: str
    ) -> dict:
        if repository is None:
            raise HTTPException(
                status_code=503, detail={"code": "app_database_unavailable"}
            )
        result = await repository.get_property_context(
            namespace, object_code, property_code
        )
        if result is None:
            raise HTTPException(
                status_code=404, detail={"code": "ontology_property_not_found"}
            )
        return result

    return router
