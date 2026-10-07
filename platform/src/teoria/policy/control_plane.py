from __future__ import annotations

import gzip
import hmac
import json
from pathlib import Path
from typing import Any, Protocol

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from teoria.config import Settings, bootstrap_settings


class PolicyTelemetryRepository(Protocol):
    def record_decisions(self, events: list[dict[str, Any]]) -> None: ...
    def record_status(self, status: dict[str, Any]) -> None: ...


class PostgresPolicyTelemetryRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_decisions(self, events: list[dict[str, Any]]) -> None:
        rows = [
            (
                event["decision_id"], json.dumps(event.get("labels") or {}),
                json.dumps(event.get("bundles") or {}), event.get("path"),
                json.dumps(event.get("input")), json.dumps(event.get("result")),
                event.get("requested_by"), event.get("timestamp"), json.dumps(event),
            )
            for event in events
            if isinstance(event, dict) and event.get("decision_id")
        ]
        if not rows:
            return
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO policy.opa_decision_logs (
                        decision_id, labels, bundles, decision_path, input_document,
                        result_document, requested_by, decided_at, event
                    ) VALUES (%s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    rows,
                )

    def record_status(self, status: dict[str, Any]) -> None:
        labels = status.get("labels") or {}
        instance_id = str(labels.get("id") or "unknown")
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO policy.opa_status_reports (instance_id, report)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (instance_id) DO UPDATE
                    SET report = EXCLUDED.report, received_at = now()
                    """,
                    (instance_id, json.dumps(status)),
                )


def create_policy_control_plane_app(
    *,
    settings: Settings | None = None,
    repository: PolicyTelemetryRepository | None = None,
) -> FastAPI:
    resolved = settings or bootstrap_settings()
    if not resolved.opa_control_plane_token:
        raise RuntimeError("TEORIA_OPA_CONTROL_PLANE_TOKEN is required")
    if repository is None:
        if not resolved.app_database_url:
            raise RuntimeError("TEORIA_APP_DATABASE_URL is required")
        repository = PostgresPolicyTelemetryRepository(resolved.app_database_url)
    bundle_path = Path(resolved.opa_bundle_path)
    app = FastAPI(title="Teoria OPA Control Plane", version="1.0.0")

    def authorize(authorization: str | None) -> None:
        expected = f"Bearer {resolved.opa_control_plane_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    @app.get("/health")
    async def health():
        if not bundle_path.is_file():
            return JSONResponse(
                status_code=503, content={"status": "bundle_unavailable"}
            )
        return {"status": "ok"}

    @app.get("/bundles/teoria.tar.gz")
    async def bundle(authorization: str | None = Header(default=None)):
        authorize(authorization)
        if not bundle_path.is_file():
            raise HTTPException(status_code=503, detail={"code": "bundle_unavailable"})
        return FileResponse(bundle_path, media_type="application/gzip")

    @app.post("/logs", status_code=204)
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
                raise HTTPException(status_code=400, detail={"code": "invalid_gzip"}) from exc
        try:
            events = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail={"code": "invalid_json"}) from exc
        if not isinstance(events, list):
            raise HTTPException(status_code=400, detail={"code": "decision_log_array_required"})
        repository.record_decisions(events)

    @app.post("/status", status_code=204)
    async def status(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        authorize(authorization)
        report = await request.json()
        if not isinstance(report, dict):
            raise HTTPException(status_code=400, detail={"code": "status_object_required"})
        repository.record_status(report)

    return app


def app_factory() -> FastAPI:
    return create_policy_control_plane_app()
