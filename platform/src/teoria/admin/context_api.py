from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from teoria.context import ContextEngine


class ContextQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    as_of: date | None = None


def create_context_router(engine: ContextEngine | None) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/context", tags=["context"])

    @router.get("/resolve")
    async def resolve(
        term: str = Query(min_length=1, max_length=200),
        purpose: str | None = Query(default=None, pattern="^(analytics|realtime|definition)$"),
    ) -> dict:
        if engine is None:
            raise HTTPException(status_code=503, detail={"code": "context_engine_unavailable"})
        try:
            result = await engine.resolve(term.strip(), purpose=purpose)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail={"code": "invalid_published_artifact", "message": str(exc)}) from exc
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "business_term_not_resolved"})
        return result

    @router.post("/query")
    async def query(request: ContextQueryRequest) -> dict:
        if engine is None:
            raise HTTPException(status_code=503, detail={"code": "context_engine_unavailable"})
        try:
            return await engine.query(request.question.strip(), as_of=request.as_of)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "context_not_resolved", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "context_runtime_unavailable", "message": str(exc)}) from exc

    return router
