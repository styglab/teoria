"""OPA control-plane HTTP routes; the process entrypoint supplies settings and persistence."""

from __future__ import annotations
import gzip
import hmac
import json
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from teoria.features.access_control.policy.telemetry_repository import (
    PolicyTelemetryRepository,
)


def create_policy_control_plane_router(
    *, token: str, bundle_path: Path, repository: PolicyTelemetryRepository
) -> APIRouter:
    router = APIRouter()

    def authorize(authorization: str | None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    @router.get("/health")
    async def health():
        if not bundle_path.is_file():
            return JSONResponse(
                status_code=503, content={"status": "bundle_unavailable"}
            )
        return {"status": "ok"}

    @router.get("/bundles/teoria.tar.gz")
    async def bundle(authorization: str | None = Header(default=None)):
        authorize(authorization)
        if not bundle_path.is_file():
            raise HTTPException(status_code=503, detail={"code": "bundle_unavailable"})
        return FileResponse(bundle_path, media_type="application/gzip")

    @(router.post("/logs", status_code=204))
    async def decision_logs(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        authorize(authorization)
        payload = await request.body()
        if request.headers.get("content-encoding", "").lower() == "gzip":
            try:
                payload = gzip.decompress(payload)
            except gzip.BadGzipFile as exc:
                raise HTTPException(
                    status_code=400, detail={"code": "invalid_gzip"}
                ) from exc
        try:
            events = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail={"code": "invalid_json"}
            ) from exc
        if not isinstance(events, list):
            raise HTTPException(
                status_code=400, detail={"code": "decision_log_array_required"}
            )
        await repository.record_decisions(events)

    @(router.post("/status", status_code=204))
    async def status(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        authorize(authorization)
        report = await request.json()
        if not isinstance(report, dict):
            raise HTTPException(
                status_code=400, detail={"code": "status_object_required"}
            )
        await repository.record_status(report)

    return router
