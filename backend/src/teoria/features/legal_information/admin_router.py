from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.legal_information.search import LawSearchReader, LawSearchRequest


def create_law_search_router(
    reader: LawSearchReader | None, authorizer: AdminAuthorizer
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/admin/legal-information",
        tags=["legal-information"],
        dependencies=[Depends(authorizer.require())],
    )

    def require_reader():
        if reader is None:
            raise HTTPException(
                status_code=503, detail={"code": "law_search_database_not_configured"}
            )
        return reader

    @(router.post("/search"))
    async def search(request: LawSearchRequest):
        try:
            return await require_reader().search(request)
        except psycopg.Error:
            raise HTTPException(
                status_code=503, detail={"code": "law_search_database_unavailable"}
            ) from None

    @router.get("/documents/{snapshot_id}")
    async def document(
        snapshot_id: UUID,
        path: str = Query(..., min_length=1, max_length=1000),
        max_chars: int = Query(20000, ge=1000, le=50000),
    ):
        try:
            result = await require_reader().get_document(
                snapshot_id, path, max_chars=max_chars
            )
        except psycopg.Error:
            raise HTTPException(
                status_code=503, detail={"code": "law_search_database_unavailable"}
            ) from None
        if result is None:
            raise HTTPException(
                status_code=404, detail={"code": "law_document_not_found"}
            )
        return result

    return router
