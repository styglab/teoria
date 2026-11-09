"""Customer churn service discovery and test endpoint for the optional example."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from teoria.examples.customer_churn import MODEL_NAME
from teoria.examples.customer_churn.inference import PredictionInput
from teoria.platform.access_control.auth import AdminAuthorizer, AdminPrincipal


async def describe_models(
    client: httpx.AsyncClient, inference_url: str, selected: str | None
) -> dict:
    try:
        response = await client.get(inference_url.rstrip("/") + "/health")
        health = response.json() if response.is_success else {"status": "not_ready"}
    except httpx.HTTPError:
        health = {"status": "unavailable"}
    return {
        "demo_model_name": MODEL_NAME,
        "serving": {**health, "model_name": MODEL_NAME},
        "synthetic": selected == MODEL_NAME,
    }


def create_customer_churn_router(
    *,
    authorizer: AdminAuthorizer,
    client: httpx.AsyncClient,
    enabled: bool,
    inference_url: str,
    inference_token: str | None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/model-operations", tags=["model-operations"])

    def require_enabled():
        if not enabled:
            raise HTTPException(503, detail={"code": "model_operations_not_configured"})

    @router.get("/services")
    async def services(principal: AdminPrincipal = Depends(authorizer.require())):
        require_enabled()
        try:
            response = await client.get(inference_url.rstrip("/") + "/health")
            health = response.json() if response.is_success else {"status": "not_ready"}
        except httpx.HTTPError:
            health = {"status": "unavailable"}
        return {
            "items": [
                {
                    "id": "customer-churn",
                    "name": "고객 이탈 예측",
                    "endpoint": "/inference-api/predict",
                    "method": "POST",
                    "model_name": MODEL_NAME,
                    "model_version": health.get("model_version"),
                    "status": health.get("status", "unavailable"),
                    "environment": "합성 데이터 검증",
                    "description": "합성 고객의 이용 이력으로 이탈 확률을 예측하는 검증용 서비스입니다.",
                    "request_schema": PredictionInput.model_json_schema(),
                    "deployment_pipeline_id": "demo-deploy-customer-churn",
                }
            ]
        }

    @router.post("/predict")
    async def predict(
        payload: PredictionInput,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        require_enabled()
        try:
            response = await client.post(
                inference_url.rstrip("/") + "/predict",
                json=payload.model_dump(),
                headers={"Authorization": "Bearer " + (inference_token or "")},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            raise HTTPException(
                503, detail={"code": "demo_inference_unavailable"}
            ) from None

    return router
