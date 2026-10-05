from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


class SuggestionRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create(
        self,
        *,
        target_type: str,
        target_ref: str,
        suggestion_type: str,
        proposed_value: Any,
        confidence: float,
        rationale: str | None,
        risk_level: str,
        model_provider: str,
        model_name: str,
        model_version: str | None,
        policy_version: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        suggestion_id = uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                """
                INSERT INTO intelligence.suggestions (
                    suggestion_id, target_type, target_ref, suggestion_type,
                    proposed_value, confidence, rationale, risk_level,
                    model_provider, model_name, model_version, policy_version,
                    status
                ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,'pending')
                """,
                (
                    suggestion_id, target_type, target_ref, suggestion_type,
                    json.dumps(proposed_value, ensure_ascii=False), confidence,
                    rationale, risk_level, model_provider, model_name,
                    model_version, policy_version,
                ),
            )
            for item in evidence:
                connection.execute(
                    """
                    INSERT INTO intelligence.suggestion_evidence (
                        evidence_id, suggestion_id, evidence_type, source_ref,
                        excerpt, content_hash, observed_at, provenance
                    ) VALUES (%s,%s,%s,%s,%s,%s,COALESCE(%s::timestamptz,now()),%s::jsonb)
                    """,
                    (
                        uuid4(), suggestion_id, item["evidence_type"],
                        item["source_ref"], item.get("excerpt"),
                        item.get("content_hash"), item.get("observed_at"),
                        json.dumps(item.get("provenance", {}), ensure_ascii=False),
                    ),
                )
        return self.get(suggestion_id)

    def list(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        query = "SELECT * FROM intelligence.suggestions"
        params: list[Any] = []
        if status:
            query += " WHERE status = %s"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return [_jsonable(dict(row)) for row in connection.execute(query, params).fetchall()]

    def get(self, suggestion_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM intelligence.suggestions WHERE suggestion_id = %s",
                (suggestion_id,),
            ).fetchone()
            if row is None:
                raise KeyError(str(suggestion_id))
            evidence = connection.execute(
                "SELECT * FROM intelligence.suggestion_evidence WHERE suggestion_id = %s ORDER BY observed_at",
                (suggestion_id,),
            ).fetchall()
            reviews = connection.execute(
                "SELECT * FROM intelligence.reviews WHERE suggestion_id = %s ORDER BY reviewed_at",
                (suggestion_id,),
            ).fetchall()
        result = _jsonable(dict(row))
        result["evidence"] = [_jsonable(dict(item)) for item in evidence]
        result["reviews"] = [_jsonable(dict(item)) for item in reviews]
        return result

    def review(self, suggestion_id: UUID, *, decision: str, reviewer: str, comment: str | None) -> dict[str, Any]:
        status_by_decision = {
            "approve": "approved", "reject": "rejected",
            "request_changes": "changes_requested", "supersede": "rejected",
        }
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            current = connection.execute(
                "SELECT status FROM intelligence.suggestions WHERE suggestion_id = %s FOR UPDATE",
                (suggestion_id,),
            ).fetchone()
            if current is None:
                raise KeyError(str(suggestion_id))
            if current["status"] not in {"pending", "changes_requested"}:
                raise ValueError(f"Suggestion cannot be reviewed from status {current['status']}")
            connection.execute(
                "INSERT INTO intelligence.reviews (review_id,suggestion_id,decision,reviewer,comment) VALUES (%s,%s,%s,%s,%s)",
                (uuid4(), suggestion_id, decision, reviewer, comment),
            )
            connection.execute(
                "UPDATE intelligence.suggestions SET status = %s WHERE suggestion_id = %s",
                (status_by_decision[decision], suggestion_id),
            )
        return self.get(suggestion_id)

    def start_application(self, suggestion_id: UUID, *, target_system: str = "openmetadata") -> UUID:
        application_id = uuid4()
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO intelligence.change_applications (
                    change_application_id, suggestion_id, target_system,
                    idempotency_key, status, attempted_at
                ) VALUES (%s,%s,%s,%s,'applying',now())
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    status = 'applying', attempted_at = now(), error_code = NULL
                """,
                (application_id, suggestion_id, target_system, f"suggestion:{suggestion_id}:{target_system}"),
            )
        return application_id

    def finish_application(self, suggestion_id: UUID, *, applied: bool, external_change_ref: str | None = None, error_code: str | None = None) -> None:
        status = "applied" if applied else "failed"
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                UPDATE intelligence.change_applications
                   SET status = %s, external_change_ref = %s, error_code = %s,
                       applied_at = CASE WHEN %s THEN now() ELSE NULL END
                 WHERE suggestion_id = %s AND status = 'applying'
                """,
                (status, external_change_ref, error_code, applied, suggestion_id),
            )
            connection.execute(
                "UPDATE intelligence.suggestions SET status = %s WHERE suggestion_id = %s",
                (status, suggestion_id),
            )


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    for key, item in tuple(value.items()):
        if hasattr(item, "isoformat"):
            value[key] = item.isoformat()
        elif not isinstance(item, (str, int, float, bool, list, dict, type(None))):
            value[key] = str(item)
    return value
