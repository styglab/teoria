from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from teoria.context import ContextEngine
from teoria.admin.auth import AdminAuthorizer, AdminPrincipal
from teoria.policy import PolicyDeniedError, PolicyEvaluationError


class ContextQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    as_of: date | None = None


def create_context_router(engine: ContextEngine | None, authorizer: AdminAuthorizer) -> APIRouter:
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

    async def run(
        operation: str,
        request: ContextQueryRequest,
        principal: AdminPrincipal,
    ) -> dict:
        if engine is None:
            raise HTTPException(status_code=503, detail={"code": "context_engine_unavailable"})
        try:
            handler = engine.plan if operation == "plan" else engine.query
            return await handler(
                request.question.strip(),
                as_of=request.as_of,
                actor=principal.actor,
                roles=principal.roles,
            )
        except PolicyDeniedError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "policy_denied",
                    "reason": exc.decision.reason,
                    "decision_id": exc.decision.decision_id,
                },
            ) from exc
        except PolicyEvaluationError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "policy_unavailable", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "context_not_resolved", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"code": "context_runtime_unavailable", "message": str(exc)}) from exc

    @router.post("/plan")
    async def plan(
        request: ContextQueryRequest,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        return await run("plan", request, principal)

    @router.post("/execute")
    async def execute(
        request: ContextQueryRequest,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        return await run("execute", request, principal)

    @router.post("/query", deprecated=True)
    async def query(
        request: ContextQueryRequest,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ) -> dict:
        return await run("execute", request, principal)

    return router
