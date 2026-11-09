"""MLflow model registry and configured inference services for the Admin workspace."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from teoria.integrations.mlflow.models import (
    read_model_run,
    search_model_versions,
    search_registered_models,
)
from teoria.platform.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.platform.workflow_management.admin_router import create_workflow_router


def create_model_operations_router(
    *,
    authorizer: AdminAuthorizer,
    client: httpx.AsyncClient,
    enabled: bool,
    workflow_catalog: dict,
    prepare_run,
    prefect_url: str,
    prefect_auth: str,
    mlflow_url: str,
    inference_token: str | None = None,
    default_model_name: str | None = None,
    parameter_names: frozenset[str] = frozenset(),
    model_context: Callable[[str | None], Awaitable[dict]] | None = None,
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
            catalog=workflow_catalog,
            prepare_run=prepare_run,
            prefix="",
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
            data = await search_registered_models(
                client, mlflow_url, query=q, page_token=page_token
            )
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
            data = await search_model_versions(
                client, mlflow_url, name, page_token=version_token
            )
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

        try:
            catalog = await registry()
            selected = model_name or (
                catalog["registered_models"][0]["name"]
                if catalog["registered_models"]
                else default_model_name
            )
            items, next_version_token = (
                await versions(selected) if selected else ([], None)
            )
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "mlflow_unavailable"}) from None
        items.sort(key=lambda item: int(item["version"]), reverse=True)
        semaphore = asyncio.Semaphore(4)

        async def enrich(item):
            if not item.get("run_id"):
                return item
            try:
                async with semaphore:
                    run = await read_model_run(client, mlflow_url, item["run_id"])
                data = run["data"]
                tags = {tag["key"]: tag["value"] for tag in data.get("tags", [])}
                return {
                    **item,
                    "experiment_id": run.get("info", {}).get("experiment_id"),
                    "prefect_run_id": tags.get("teoria.prefect_flow_run_id"),
                    "pipeline_run_id": tags.get("teoria.prefect_pipeline_run_id"),
                    "metrics": {
                        m["key"]: m["value"] for m in data.get("metrics", [])[:50]
                    },
                    "parameters": {
                        p["key"]: p["value"]
                        for p in data.get("params", [])
                        if p["key"] in parameter_names
                    },
                }
            except (httpx.HTTPError, KeyError, ValueError):
                return {**item, "metrics_unavailable": True}

        items = await asyncio.gather(*(enrich(item) for item in items))
        return {
            **catalog,
            "model_name": selected,
            "next_version_token": next_version_token,
            "items": items,
            **(await model_context(selected) if model_context else {}),
        }

    return router
