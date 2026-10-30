"""MLflow model registry and configured inference services for the Admin workspace."""

from __future__ import annotations

import asyncio
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.model_operations.inference import PredictionInput
from teoria.integrations.mlflow.models import MODEL_NAME
from teoria.features.workflow_management.admin_router import create_workflow_router


def create_model_operations_router(
    *,
    authorizer: AdminAuthorizer,
    client: httpx.AsyncClient,
    enabled: bool,
    prefect_url: str,
    prefect_auth: str,
    mlflow_url: str,
    inference_url: str,
    inference_token: str | None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/model-operations", tags=["model-operations"])

    def require_enabled():
        if not enabled:
            raise HTTPException(503, detail={"code": "model_operations_not_configured"})

    router.include_router(
        create_workflow_router(
            authorizer=authorizer,
            client=client,
            prefect_url=prefect_url,
            prefect_auth=prefect_auth,
            mlops_enabled=enabled,
            semantic_enabled=False,
            formatid_enabled=False,
            legal_enabled=False,
            prefix="",
            include_internal=True,
            inference_token=inference_token,
        )
    )

    @router.get("/status")
    async def status(principal: AdminPrincipal = Depends(authorizer.require())):
        return {"enabled": enabled}

    def clean(value) -> str:
        text = str(value or "")[:12000]
        for secret in (prefect_auth, inference_token, authorizer.token):
            if secret:
                text = text.replace(secret, "[redacted]")
        text = re.sub(
            r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text
        )
        text = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/-]+=*", r"\1[redacted]", text)
        return text

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

    @router.get("/models")
    async def models(
        model_name: str | None = Query(None, max_length=256),
        q: str = Query("", max_length=100),
        page_token: str | None = Query(None, max_length=2048),
        version_token: str | None = Query(None, max_length=2048),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        require_enabled()

        async def registry():
            response = await client.get(
                mlflow_url.rstrip("/") + "/api/2.0/mlflow/registered-models/search",
                params={
                    "max_results": 25,
                    **(
                        {
                            "filter": "name ILIKE '%"
                            + q.replace("\\", "\\\\").replace("'", "\\'")
                            + "%'"
                        }
                        if q
                        else {}
                    ),
                    **({"page_token": page_token} if page_token else {}),
                },
            )
            response.raise_for_status()
            data = response.json()
            return {
                "registered_models": [
                    {
                        "name": item["name"],
                        "description": clean(item.get("description")),
                        "last_updated_timestamp": item.get("last_updated_timestamp"),
                        "aliases": item.get("aliases", []),
                        "tags": [
                            {"key": clean(tag["key"]), "value": clean(tag["value"])}
                            for tag in item.get("tags", [])[:20]
                        ],
                        "latest_versions": [
                            {"version": v["version"]}
                            for v in item.get("latest_versions", [])
                        ],
                    }
                    for item in data.get("registered_models", [])
                ],
                "next_page_token": data.get("next_page_token"),
            }

        async def versions(name):
            escaped = name.replace("\\", "\\\\").replace("'", "\\'")
            response = await client.get(
                mlflow_url.rstrip("/") + "/api/2.0/mlflow/model-versions/search",
                params={
                    "filter": f"name = '{escaped}'",
                    "max_results": 25,
                    "order_by": "version_number DESC",
                    **({"page_token": version_token} if version_token else {}),
                },
            )
            response.raise_for_status()
            data = response.json()
            return [
                {
                    key: version.get(key)
                    for key in (
                        "name",
                        "version",
                        "status",
                        "run_id",
                        "creation_timestamp",
                    )
                }
                for version in data.get("model_versions", [])
            ], data.get("next_page_token")

        async def health():
            try:
                response = await client.get(inference_url.rstrip("/") + "/health")
                return (
                    response.json() if response.is_success else {"status": "not_ready"}
                )
            except httpx.HTTPError:
                return {"status": "unavailable"}

        try:
            catalog, serving = await asyncio.gather(registry(), health())
            selected = model_name or (
                catalog["registered_models"][0]["name"]
                if catalog["registered_models"]
                else MODEL_NAME
            )
            items, next_version_token = await versions(selected)
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "mlflow_unavailable"}) from None
        items.sort(key=lambda item: int(item["version"]), reverse=True)
        semaphore = asyncio.Semaphore(4)

        async def enrich(item):
            if not item.get("run_id"):
                return item
            try:
                async with semaphore:
                    response = await client.get(
                        mlflow_url.rstrip("/") + "/api/2.0/mlflow/runs/get",
                        params={"run_id": item["run_id"]},
                    )
                    response.raise_for_status()
                data = response.json()["run"]["data"]
                tags = {tag["key"]: tag["value"] for tag in data.get("tags", [])}
                return {
                    **item,
                    "experiment_id": response.json()["run"]
                    .get("info", {})
                    .get("experiment_id"),
                    "prefect_run_id": tags.get("teoria.prefect_flow_run_id"),
                    "pipeline_run_id": tags.get("teoria.prefect_pipeline_run_id"),
                    "metrics": {
                        m["key"]: m["value"] for m in data.get("metrics", [])[:50]
                    },
                    "parameters": {
                        p["key"]: p["value"]
                        for p in data.get("params", [])
                        if p["key"]
                        in {
                            "dataset_version",
                            "dataset_sha256",
                            "split_seed",
                            "personal_attributes_in_features",
                        }
                    },
                }
            except (httpx.HTTPError, KeyError, ValueError):
                return {**item, "metrics_unavailable": True}

        items = await asyncio.gather(*(enrich(item) for item in items))
        return {
            **catalog,
            "model_name": selected,
            "demo_model_name": MODEL_NAME,
            "next_version_token": next_version_token,
            "items": items,
            "serving": {**serving, "model_name": MODEL_NAME},
            "synthetic": selected == MODEL_NAME,
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
