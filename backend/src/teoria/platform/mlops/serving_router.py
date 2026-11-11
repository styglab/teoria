"""Authenticated deployment references and inference through a fixed recorded endpoint."""
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from teoria.platform.mlops.deployments import DeploymentRepository


def create_serving_router(*, authorizer, client, database_url, enabled):
    router = APIRouter(prefix="/v1/admin/model-operations", tags=["model-operations"])
    repository = DeploymentRepository(database_url) if database_url and enabled else None

    def require_repository():
        if repository is None:
            raise HTTPException(503, detail={"code": "model_operations_not_configured"})
        return repository

    @router.get("/deployments")
    async def deployments(principal=Depends(authorizer.require())):
        items = await require_repository().list()
        semaphore = asyncio.Semaphore(4)
        async def health(item):
            if item['status'] != 'ready':
                return {**item, "health": "stopped"}
            try:
                async with semaphore:
                    response = await client.get(item['endpoint'] + item['specification']['readiness_path'], timeout=5)
                return {**item, "health": "ok" if response.is_success else "unavailable"}
            except httpx.HTTPError:
                return {**item, "health": "unavailable"}
        return {"items": await asyncio.gather(*(health(item) for item in items))}

    @router.post("/deployments/{deployment_id}/predict")
    async def predict(deployment_id: str, request: Request, principal=Depends(authorizer.require())):
        item = await require_repository().get(deployment_id)
        if not item or item['status'] != 'ready':
            raise HTTPException(404, detail={"code": "serving_deployment_not_ready"})
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise HTTPException(413, "prediction_request_too_large")
        try:
            async with client.stream("POST", item['endpoint'] + '/predict', content=bytes(data),
                                     headers={"Content-Type": "application/json"}, timeout=30) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 4 * 1024 * 1024:
                        raise HTTPException(502, "prediction_response_too_large")
                return Response(bytes(body), status_code=response.status_code, media_type="application/json")
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "serving_unavailable"}) from None

    return router
