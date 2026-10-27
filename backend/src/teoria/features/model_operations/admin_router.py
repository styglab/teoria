"""Authenticated, allowlisted demo pipeline controls; no arbitrary code or Docker API."""

from __future__ import annotations

import asyncio
import re
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.model_operations.inference import PredictionInput
from teoria.integrations.mlflow.models import MODEL_NAME
from teoria.integrations.prefect.http_client import PrefectManagementClient

PIPELINES = {
    "demo-seed-customers": "합성 고객 데이터 준비",
    "openmetadata-postgres-metadata-sync": "데이터 자산 메타데이터 동기화",
    "demo-train-customer-churn": "고객 이탈 모델 학습·평가",
    "demo-deploy-customer-churn": "고정 모델 버전 서빙 배포·복구",
}


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    model_version: int | None = Field(default=None, ge=1, strict=True)


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
    prefect = (
        PrefectManagementClient(client, prefect_url, prefect_auth)
        if prefect_auth
        else None
    )

    def require_enabled():
        if not enabled or prefect is None:
            raise HTTPException(503, detail={"code": "model_operations_not_configured"})

    async def deployment_list():
        require_enabled()
        return await prefect.deployments(list(PIPELINES))

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

    def run_summary(item):
        return {
            key: item.get(key)
            for key in (
                "id",
                "name",
                "deployment_id",
                "state_type",
                "start_time",
                "end_time",
                "created",
                "expected_start_time",
                "total_run_time",
                "run_count",
            )
        }

    @router.get("/pipelines")
    async def pipelines(
        pipeline_id: str | None = None,
        state: Literal[
            "COMPLETED",
            "RUNNING",
            "SCHEDULED",
            "PENDING",
            "FAILED",
            "CRASHED",
            "CANCELLED",
        ]
        | None = None,
        offset: int = Query(0, ge=0, le=100000),
        limit: int = Query(25, ge=1, le=50),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        if not enabled:
            return {"enabled": False, "items": [], "runs": []}
        try:
            deployments = await deployment_list()
            if pipeline_id is not None and pipeline_id not in PIPELINES:
                raise HTTPException(404, "pipeline_not_found")
            ids = [
                item["id"]
                for item in deployments
                if not pipeline_id or item["name"] == pipeline_id
            ]
            runs, total, latest = await asyncio.gather(
                prefect.runs(ids, limit=limit, offset=offset, state=state),
                prefect.run_count(ids, state),
                asyncio.gather(
                    *(prefect.runs([item["id"]], limit=1) for item in deployments)
                ),
            )
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None
        by_name = {item["name"]: item for item in deployments}
        latest_by_id = {
            item["id"]: run_summary(items[0]) if items else None
            for item, items in zip(deployments, latest)
        }
        return {
            "enabled": True,
            "items": [
                {
                    "id": name,
                    "name": label,
                    "available": name in by_name,
                    "paused": by_name.get(name, {}).get("paused", False),
                    "deployment_id": by_name.get(name, {}).get("id"),
                    "requires_model_version": name == "demo-deploy-customer-churn",
                    "description": by_name.get(name, {}).get("description"),
                    "work_pool_name": by_name.get(name, {}).get("work_pool_name"),
                    "latest_run": latest_by_id.get(by_name.get(name, {}).get("id")),
                }
                for name, label in PIPELINES.items()
            ],
            "runs": [run_summary(item) for item in runs],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @router.get("/runs/{run_id}")
    async def run_detail(
        run_id: UUID, principal: AdminPrincipal = Depends(authorizer.require())
    ):
        require_enabled()
        try:
            item = await prefect.run(str(run_id))
            deployments = await deployment_list()
            deployment = next(
                (d for d in deployments if d["id"] == item.get("deployment_id")), None
            )
            if deployment is None:
                raise HTTPException(404, "model_pipeline_run_not_found")
            tasks, logs = await asyncio.gather(
                prefect.tasks(str(run_id)), prefect.logs(str(run_id))
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                404 if exc.response.status_code == 404 else 503,
                detail={"code": "pipeline_run_unavailable"},
            ) from None
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None
        return {
            "run": {
                **run_summary(item),
                "pipeline_id": deployment["name"],
                "parameters": {
                    k: clean(v)
                    for k, v in item.get("parameters", {}).items()
                    if k in {"model_version", "requested_by"}
                },
                "message": clean((item.get("state") or {}).get("message")),
            },
            "tasks": [
                {
                    **run_summary(task),
                    "message": clean((task.get("state") or {}).get("message")),
                }
                for task in tasks
            ],
            "logs": [
                {
                    "id": log["id"],
                    "timestamp": log["timestamp"],
                    "level": log["level"],
                    "task_run_id": log.get("task_run_id"),
                    "message": clean(log.get("message")),
                }
                for log in reversed(logs)
            ],
            "tasks_limited": len(tasks) >= 100,
            "logs_limited": len(logs) >= 100,
        }

    @router.post("/pipelines/{pipeline_id}/runs", status_code=202)
    async def run(
        pipeline_id: str,
        payload: PipelineRunRequest,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        if pipeline_id not in PIPELINES:
            raise HTTPException(404, "pipeline_not_found")
        if (
            pipeline_id == "demo-deploy-customer-churn"
            and payload.model_version is None
        ):
            raise HTTPException(422, "model_version_required")
        if (
            pipeline_id != "demo-deploy-customer-churn"
            and payload.model_version is not None
        ):
            raise HTTPException(422, "model_version_not_applicable")
        try:
            deployment = next(
                (
                    item
                    for item in await deployment_list()
                    if item["name"] == pipeline_id
                ),
                None,
            )
            if deployment is None or deployment.get("paused"):
                raise HTTPException(409, "pipeline_not_available")
            parameters = (
                {}
                if pipeline_id == "openmetadata-postgres-metadata-sync"
                else {"requested_by": principal.actor}
            )
            if payload.model_version is not None:
                parameters["model_version"] = payload.model_version
            result = await prefect.create_run(
                deployment["id"],
                parameters,
                actor=principal.actor,
                key=f"{principal.actor}:{pipeline_id}:{payload.idempotency_key}",
            )
            return {"flow_run_id": result["id"], "name": result["name"]}
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None

    @router.get("/models")
    async def models(principal: AdminPrincipal = Depends(authorizer.require())):
        require_enabled()

        async def versions():
            response = await client.get(
                mlflow_url.rstrip("/") + "/api/2.0/mlflow/model-versions/search",
                params={"filter": f"name = '{MODEL_NAME}'", "max_results": 20},
            )
            response.raise_for_status()
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
                for version in response.json().get("model_versions", [])
            ]

        async def health():
            try:
                response = await client.get(inference_url.rstrip("/") + "/health")
                return (
                    response.json() if response.is_success else {"status": "not_ready"}
                )
            except httpx.HTTPError:
                return {"status": "unavailable"}

        try:
            items, serving = await asyncio.gather(versions(), health())
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
                return {
                    **item,
                    "metrics": {
                        m["key"]: m["value"]
                        for m in data.get("metrics", [])
                        if m["key"]
                        in {"accuracy", "roc_auc", "training_rows", "evaluation_rows"}
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
            "model_name": MODEL_NAME,
            "items": items,
            "serving": serving,
            "synthetic": True,
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
