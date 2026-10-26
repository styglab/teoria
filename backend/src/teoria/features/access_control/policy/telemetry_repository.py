from __future__ import annotations

import json
from typing import Any, Protocol

from teoria.integrations.application_database.postgres import connect


class PolicyTelemetryRepository(Protocol):
    async def record_decisions(self, events: list[dict[str, Any]]) -> None: ...
    async def record_status(self, status: dict[str, Any]) -> None: ...


class PostgresPolicyTelemetryRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def record_decisions(self, events: list[dict[str, Any]]) -> None:
        rows = [
            (
                event["decision_id"],
                json.dumps(event.get("labels") or {}),
                json.dumps(event.get("bundles") or {}),
                event.get("path"),
                json.dumps(event.get("input")),
                json.dumps(event.get("result")),
                event.get("requested_by"),
                event.get("timestamp"),
                json.dumps(event),
            )
            for event in events
            if isinstance(event, dict) and event.get("decision_id")
        ]
        if not rows:
            return
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO policy.opa_decision_logs (
                        decision_id, labels, bundles, decision_path, input_document,
                        result_document, requested_by, decided_at, event
                    ) VALUES (%s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    rows,
                )

    async def record_status(self, status: dict[str, Any]) -> None:
        labels = status.get("labels") or {}
        instance_id = str(labels.get("id") or "unknown")
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO policy.opa_status_reports (instance_id, report)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (instance_id) DO UPDATE
                    SET report = EXCLUDED.report, received_at = now()
                    """,
                    (instance_id, json.dumps(status)),
                )
