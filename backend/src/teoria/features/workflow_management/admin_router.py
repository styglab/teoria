"""Authenticated Prefect catalog, schedules and manual executions."""

from __future__ import annotations
import asyncio
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from uuid import UUID
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.workflow_management.catalog import workflow_catalog
from teoria.integrations.prefect.http_client import PrefectManagementClient

logger = logging.getLogger(__name__)


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID
    deploy: bool | None = Field(default=None, strict=True)
    model_version: int | None = Field(default=None, ge=1, strict=True)
    manifest: dict | None = None


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool | None = Field(default=None, strict=True)
    cron: str | None = Field(default=None, min_length=5, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_change(self):
        if self.active is None and self.cron is None:
            raise ValueError("schedule change is empty")
        if (self.cron is None) != (self.timezone is None):
            raise ValueError("cron and timezone must be supplied together")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("invalid timezone") from None
        return self


def create_workflow_router(
    *,
    authorizer: AdminAuthorizer,
    client: httpx.AsyncClient,
    prefect_url: str,
    prefect_auth: str,
    mlops_enabled: bool,
    prefix: str = "/v1/admin/workflows",
    include_internal: bool = False,
    inference_token: str | None = None,
    semantic_enabled: bool = True,
    formatid_enabled: bool = True,
    legal_enabled: bool = True,
):
    router = APIRouter(prefix=prefix, tags=["workflows"])
    prefect = (
        PrefectManagementClient(client, prefect_url, prefect_auth)
        if prefect_auth
        else None
    )
    catalog = workflow_catalog(
        mlops_enabled,
        include_internal,
        semantic_enabled=semantic_enabled,
        formatid_enabled=formatid_enabled,
        legal_enabled=legal_enabled,
    )
    PIPELINES = {key: item[0] for key, item in catalog.items()}

    def require_enabled():
        if prefect is None:
            raise HTTPException(503, detail={"code": "prefect_not_configured"})

    async def deployment_list():
        require_enabled()
        return await prefect.deployments(list(PIPELINES))

    def clean(value) -> str:
        text = str(value if value is not None else "")[:12000]
        for secret in (prefect_auth, inference_token, authorizer.token):
            if secret:
                text = text.replace(secret, "[redacted]")
        text = re.sub(
            r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text
        )
        text = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/-]+=*", r"\1[redacted]", text)
        return text

    def run_summary(item):
        summary = {
            key: item.get(key)
            for key in (
                "id",
                "name",
                "deployment_id",
                "state_type",
                "state_name",
                "start_time",
                "end_time",
                "created",
                "expected_start_time",
                "total_run_time",
                "run_count",
            )
        }
        parameters = item.get("parameters", {})
        summary["requested_by"] = clean(parameters.get("requested_by")) or next(
            (
                clean(tag.removeprefix("teoria:actor:"))
                for tag in item.get("tags", [])
                if tag.startswith("teoria:actor:")
            ),
            None,
        )
        summary["model_version"] = parameters.get("model_version")
        return summary

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
        if prefect is None:
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
            semaphore = asyncio.Semaphore(4)

            async def deployment_snapshot(item, upcoming=False):
                async with semaphore:
                    return (
                        await prefect.next_run(item["id"])
                        if upcoming
                        else await prefect.runs([item["id"]], limit=1)
                    )

            runs, total, latest, next_runs, running = await asyncio.gather(
                prefect.runs(ids, limit=limit, offset=offset, state=state),
                prefect.run_count(ids, state),
                asyncio.gather(*(deployment_snapshot(item) for item in deployments)),
                asyncio.gather(
                    *(deployment_snapshot(item, True) for item in deployments)
                ),
                prefect.runs(
                    [item["id"] for item in deployments], limit=50, state="RUNNING"
                ),
            )
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None
        by_name = {item["name"]: item for item in deployments}
        latest_by_id = {
            item["id"]: run_summary(items[0]) if items else None
            for item, items in zip(deployments, latest)
        }
        next_by_id = {
            item["id"]: run_summary(entries[0]) if entries else None
            for item, entries in zip(deployments, next_runs)
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
                    "category": catalog[name][1],
                    "input_kind": catalog[name][2],
                    "schedules": [
                        {
                            "id": entry["id"],
                            "active": entry.get("active", False),
                            "schedule": entry.get("schedule", {}),
                        }
                        for entry in by_name.get(name, {}).get("schedules", [])
                    ],
                    "next_run": next_by_id.get(by_name.get(name, {}).get("id")),
                    "running_runs": [
                        run_summary(run)
                        for run in running
                        if run.get("deployment_id") == by_name.get(name, {}).get("id")
                    ],
                    "can_run": "metadata_admin" in principal.roles,
                    "can_manage_schedule": "metadata_admin" in principal.roles,
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
            tasks, logs, children = await asyncio.gather(
                prefect.tasks(str(run_id)),
                prefect.logs(str(run_id)),
                prefect.subflows(str(run_id)),
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
                    if k in {"model_version", "requested_by", "deploy"}
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
            "subflows": [run_summary(child) for child in children],
            "can_cancel": "metadata_admin" in principal.roles
            and item.get("state_type") in {"RUNNING", "PENDING", "SCHEDULED", "PAUSED"},
            "tasks_limited": len(tasks) >= 100,
            "logs_limited": len(logs) >= 100,
        }

    def validate_manifest(pipeline_id, manifest):
        from teoria.features.specification_processing.models import (
            SpecificationRun,
            StandardWorkflow,
        )

        try:
            if pipeline_id == "specification-standard-workflow":
                request = StandardWorkflow.model_validate(manifest)
                extraction = request.extraction
            else:
                if (
                    pipeline_id == "specification-standard-management"
                    and "mode" not in manifest
                ):
                    from teoria.features.specification_processing.management_parameters import (
                        StandardManagementParameters,
                    )

                    return StandardManagementParameters.model_validate(
                        manifest
                    ).model_dump(mode="json", exclude_none=True)
                request = SpecificationRun.model_validate(manifest)
                extraction = request
                expected = (
                    "standard_management"
                    if pipeline_id == "specification-standard-management"
                    else "document_processing"
                )
                if request.mode != expected:
                    raise ValueError("manifest mode does not match pipeline")
            if extraction.parser_python is not None:
                raise ValueError("parser executable is configured by the worker")
            return request.model_dump(mode="json", exclude_none=True)
        except (ValidationError, ValueError):
            raise HTTPException(
                422,
                detail={
                    "code": "invalid_workflow_manifest",
                    "message": "규격서 실행 입력의 형식·필수값·mode를 확인하세요. parser_python은 Worker 설정을 사용합니다.",
                },
            ) from None

    @router.post("/pipelines/{pipeline_id}/runs", status_code=202)
    async def run(
        pipeline_id: str,
        payload: PipelineRunRequest,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        if pipeline_id not in PIPELINES:
            raise HTTPException(404, "pipeline_not_found")
        if (payload.manifest is not None) != (catalog[pipeline_id][2] == "manifest"):
            raise HTTPException(422, "manifest_required_or_not_applicable")
        if payload.deploy is not None and pipeline_id != "demo-customer-churn-pipeline":
            raise HTTPException(422, "deploy_not_applicable")
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
        manifest = (
            validate_manifest(pipeline_id, payload.manifest)
            if payload.manifest is not None
            else None
        )
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
            if catalog[pipeline_id][1] != "모델":
                parameters = {}
            if payload.manifest is not None:
                parameters["manifest"] = manifest
            if pipeline_id == "demo-customer-churn-pipeline":
                parameters["deploy"] = (
                    payload.deploy if payload.deploy is not None else False
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

    @router.post("/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(
        run_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        require_enabled()
        try:
            item = await prefect.run(str(run_id))
            allowed = {d["id"] for d in await deployment_list()}
            if item.get("deployment_id") not in allowed:
                raise HTTPException(404, "pipeline_run_not_found")
            if item.get("state_type") not in {
                "RUNNING",
                "PENDING",
                "SCHEDULED",
                "PAUSED",
                "CANCELLING",
            }:
                raise HTTPException(409, "run_is_already_finished")
            if item.get("state_type") != "CANCELLING":
                result = await prefect.cancel_run(str(run_id), principal.actor)
                # Prefect can reject the intermediate Cancelling proposal while
                # immediately moving an unstarted reservation to Cancelled.
                resulting_state = (result.get("state") or {}).get("type")
                if result.get("status") in {
                    "REJECT",
                    "ABORT",
                } and resulting_state not in {"CANCELLED", "CANCELLING"}:
                    raise HTTPException(409, "run_cancellation_rejected")
            return {"flow_run_id": str(run_id), "status": "cancellation_requested"}
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None

    @router.patch("/pipelines/{pipeline_id}/schedules/{schedule_id}")
    async def update_schedule(
        pipeline_id: str,
        schedule_id: UUID,
        payload: ScheduleUpdate,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        if pipeline_id not in PIPELINES:
            raise HTTPException(404, "pipeline_not_found")
        try:
            deployment = next(
                (d for d in await deployment_list() if d["name"] == pipeline_id), None
            )
            schedule = next(
                (
                    entry
                    for entry in (deployment or {}).get("schedules", [])
                    if str(entry["id"]) == str(schedule_id)
                ),
                None,
            )
            if deployment is None or schedule is None:
                raise HTTPException(404, "schedule_not_found")
            update = {"active": payload.active} if payload.active is not None else {}
            if payload.cron is not None:
                if "cron" not in schedule.get("schedule", {}):
                    raise HTTPException(422, "only_cron_schedules_can_be_edited_here")
                update["schedule"] = {
                    **schedule["schedule"],
                    "cron": payload.cron,
                    "timezone": payload.timezone,
                }
            await prefect.update_schedule(deployment["id"], str(schedule_id), update)
            logger.info(
                "workflow_schedule_updated actor=%s pipeline=%s schedule=%s",
                principal.actor,
                pipeline_id,
                schedule_id,
            )
            return {"id": str(schedule_id), **update}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 422}:
                raise HTTPException(
                    422,
                    detail={
                        "code": "invalid_schedule",
                        "message": "Cron 주기와 시간대 형식을 확인하세요.",
                    },
                ) from None
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None
        except httpx.HTTPError:
            raise HTTPException(503, detail={"code": "prefect_unavailable"}) from None

    return router
