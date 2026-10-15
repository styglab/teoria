from __future__ import annotations

import json
import base64
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from teoria.intelligence.application import ApplicationClaim, ApplicationStateError


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
        submitted_by: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            suggestion_id = self.insert(
                connection, target_type=target_type, target_ref=target_ref,
                suggestion_type=suggestion_type, proposed_value=proposed_value,
                confidence=confidence, rationale=rationale, risk_level=risk_level,
                model_provider=model_provider, model_name=model_name,
                model_version=model_version, policy_version=policy_version,
                submitted_by=submitted_by, evidence=evidence,
            )
        return self.get(suggestion_id)

    @staticmethod
    def insert(connection, *, target_type, target_ref, suggestion_type, proposed_value,
               confidence, rationale, risk_level, model_provider, model_name,
               model_version, policy_version, submitted_by, evidence) -> UUID:
        """Insert a pending proposal inside the caller's transaction."""
        suggestion_id = uuid4()
        connection.execute(
                """
                INSERT INTO intelligence.suggestions (
                    suggestion_id, target_type, target_ref, suggestion_type,
                    proposed_value, confidence, rationale, risk_level,
                    model_provider, model_name, model_version, policy_version,
                    submitted_by, status
                ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                """,
                (
                    suggestion_id, target_type, target_ref, suggestion_type,
                    json.dumps(proposed_value, ensure_ascii=False), confidence,
                    rationale, risk_level, model_provider, model_name,
                    model_version, policy_version, submitted_by,
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
        return suggestion_id

    def list(self, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        return self.list_page(status=status, limit=limit)["items"]

    def list_page(
        self, *, status: str | None, limit: int, after: str | None = None,
        target_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("Invalid page size")
        conditions = []
        params: list[Any] = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if target_refs is not None:
            conditions.append("target_ref = ANY(%s)")
            params.append(target_refs)
        if after:
            try:
                timestamp, identifier = json.loads(base64.urlsafe_b64decode(after).decode())
                timestamp = datetime.fromisoformat(timestamp)
                if timestamp.tzinfo is None:
                    raise ValueError("Timestamp must include timezone")
                identifier = UUID(identifier)
            except (ValueError, TypeError, UnicodeError) as exc:
                raise ValueError("Invalid suggestion cursor") from exc
            conditions.append("(created_at, suggestion_id) < (%s, %s)")
            params.extend([timestamp, identifier])
        query = "SELECT * FROM intelligence.suggestions"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, suggestion_id DESC LIMIT %s"
        params.append(limit + 1)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(query, params).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            suggestion_ids = [row["suggestion_id"] for row in rows]
            evidence_by_suggestion: dict[Any, list[dict[str, Any]]] = {
                suggestion_id: [] for suggestion_id in suggestion_ids
            }
            if suggestion_ids:
                evidence_rows = connection.execute(
                    """SELECT * FROM intelligence.suggestion_evidence
                         WHERE suggestion_id = ANY(%s) ORDER BY observed_at""",
                    (suggestion_ids,),
                ).fetchall()
                for evidence in evidence_rows:
                    evidence_by_suggestion[evidence["suggestion_id"]].append(
                        _jsonable(dict(evidence))
                    )
            result = []
            for row in rows:
                item = _jsonable(dict(row))
                item["evidence"] = evidence_by_suggestion[row["suggestion_id"]]
                result.append(item)
            self._attach_applications(connection, result)
            cursor = None
            if has_more:
                last = result[-1]
                cursor = base64.urlsafe_b64encode(json.dumps([
                    last["created_at"], last["suggestion_id"],
                ]).encode()).decode()
            return {"items": result, "next_cursor": cursor}

    @staticmethod
    def _attach_applications(connection, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        ids = [UUID(item["suggestion_id"]) for item in items]
        rows = connection.execute(
            """SELECT DISTINCT ON (suggestion_id) suggestion_id, change_application_id,
                      status, target_system, attempted_at, applied_at, attempts,
                      error_code, external_change_ref, effect_started_at, effect_succeeded_at,
                      COALESCE(lease_until>now(),false) AS lease_active
                 FROM intelligence.change_applications WHERE suggestion_id=ANY(%s)
                 ORDER BY suggestion_id, attempted_at DESC NULLS LAST""", (ids,),
        ).fetchall()
        applications = {str(row["suggestion_id"]): _jsonable(dict(row)) for row in rows}
        for item in items:
            application = applications.get(item["suggestion_id"])
            item["application"] = application
            item["next_action"] = "none"
            if item["status"] not in {"approved", "failed"}:
                continue
            if application and application["status"] == "applying" and application["lease_active"]:
                item["next_action"] = "wait"
            elif application and application["effect_started_at"]:
                item["next_action"] = "reconcile"
            elif application and application["error_code"] == "stale_evidence":
                item["next_action"] = "reanalyze"
            else:
                item["next_action"] = "retry"

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
            self._attach_applications(connection, [result])
        return result

    def application_attempts(
        self, suggestion_id: UUID, *, limit: int = 50, after: UUID | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("Invalid page size")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            if not connection.execute(
                "SELECT 1 FROM intelligence.suggestions WHERE suggestion_id=%s", (suggestion_id,),
            ).fetchone():
                raise KeyError(str(suggestion_id))
            params: list[Any] = [suggestion_id]
            cursor_filter = ""
            if after is not None:
                cursor = connection.execute(
                    """SELECT a.started_at, a.attempt_id FROM intelligence.application_attempts a
                       JOIN intelligence.change_applications c USING (change_application_id)
                       WHERE c.suggestion_id=%s AND a.attempt_id=%s""", (suggestion_id, after),
                ).fetchone()
                if cursor is None:
                    raise ValueError("Invalid application history cursor")
                cursor_filter = " AND (a.started_at,a.attempt_id)<(%s,%s)"
                params.extend([cursor["started_at"], cursor["attempt_id"]])
            params.append(limit + 1)
            rows = connection.execute(
                """SELECT a.attempt_id,a.actor,a.started_at,a.finished_at,a.outcome,a.error_code,
                          c.target_system
                   FROM intelligence.application_attempts a
                   JOIN intelligence.change_applications c USING (change_application_id)
                   WHERE c.suggestion_id=%s""" + cursor_filter +
                " ORDER BY a.started_at DESC,a.attempt_id DESC LIMIT %s", params,
            ).fetchall()
            items = [_jsonable(dict(row)) for row in rows[:limit]]
            return {"items": items, "next_cursor": items[-1]["attempt_id"] if len(rows) > limit else None}

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

    def start_application(self, suggestion_id: UUID, *, target_system: str = "openmetadata", actor: str, lease_seconds: int = 900) -> ApplicationClaim:
        if lease_seconds < 1:
            raise ValueError("Application lease must be positive")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            suggestion = connection.execute("SELECT status FROM intelligence.suggestions WHERE suggestion_id=%s FOR UPDATE", (suggestion_id,)).fetchone()
            if suggestion is None:
                raise KeyError(str(suggestion_id))
            approved = connection.execute("SELECT 1 FROM intelligence.reviews WHERE suggestion_id=%s AND decision='approve'", (suggestion_id,)).fetchone()
            if not approved or suggestion['status'] not in {'approved', 'failed', 'applied'}:
                raise ApplicationStateError("An approved suggestion is required", code="application_not_approved")
            current = connection.execute("SELECT *,COALESCE(lease_until>now(),false) AS lease_active FROM intelligence.change_applications WHERE idempotency_key=%s FOR UPDATE", (f"suggestion:{suggestion_id}:{target_system}",)).fetchone()
            if current:
                if current['status'] == 'applied':
                    raise ApplicationStateError("Suggestion is already applied", code="application_already_applied")
                if current['status'] == 'applying' and current['lease_active']:
                    raise ApplicationStateError("Application is running", code="application_in_progress")
                if current['effect_started_at'] is not None:
                    raise ApplicationStateError("Verify the existing effect before another write", code="application_reconciliation_required")
                application_id = current['change_application_id']
                connection.execute("UPDATE intelligence.application_attempts SET finished_at=now(),outcome='superseded' WHERE change_application_id=%s AND finished_at IS NULL", (application_id,))
            else:
                application_id = uuid4()
                connection.execute("INSERT INTO intelligence.change_applications (change_application_id,suggestion_id,target_system,idempotency_key,status) VALUES (%s,%s,%s,%s,'approved')", (application_id,suggestion_id,target_system,f"suggestion:{suggestion_id}:{target_system}"))
            token = uuid4()
            connection.execute("UPDATE intelligence.change_applications SET claim_token=%s,status='applying',attempted_at=now(),lease_until=now()+(%s*interval '1 second'),attempts=attempts+1,error_code=NULL WHERE change_application_id=%s", (token,lease_seconds,application_id))
            connection.execute("INSERT INTO intelligence.application_attempts (attempt_id,change_application_id,actor) VALUES (%s,%s,%s)", (token,application_id,actor))
        return ApplicationClaim(application_id, token, target_system)

    def mark_effect_started(self, claim: ApplicationClaim) -> None:
        with psycopg.connect(self.database_url) as connection:
            result = connection.execute("UPDATE intelligence.change_applications SET effect_started_at=COALESCE(effect_started_at,now()) WHERE change_application_id=%s AND claim_token=%s AND status='applying' AND lease_until>now()", (claim.application_id,claim.token))
            if result.rowcount != 1:
                raise ApplicationStateError("Application no longer owns its execution claim", code="application_claim_lost")

    def record_effect_result(self, claim: ApplicationClaim, external_change_ref: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            result = connection.execute("UPDATE intelligence.change_applications SET effect_succeeded_at=now(),external_change_ref=%s WHERE change_application_id=%s AND claim_token=%s AND status='applying' AND effect_started_at IS NOT NULL", (external_change_ref,claim.application_id,claim.token))
            if result.rowcount != 1:
                raise ApplicationStateError("Application claim does not match", code="application_claim_lost")

    def reconcile_application(self, suggestion_id: UUID, *, claim_token: UUID | str | None, external_change_ref: str, actor: str) -> None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("SELECT suggestion_id FROM intelligence.suggestions WHERE suggestion_id=%s FOR UPDATE", (suggestion_id,))
            application = connection.execute("SELECT *,COALESCE(lease_until>now(),false) AS lease_active FROM intelligence.change_applications WHERE suggestion_id=%s AND claim_token IS NOT DISTINCT FROM %s FOR UPDATE", (suggestion_id,claim_token)).fetchone()
            if application is None or (application['status']=='applying' and application['lease_active']):
                raise ApplicationStateError("Application changed during reconciliation", code="application_in_progress")
            if application['status']=='applied':
                return
            if not connection.execute("SELECT 1 FROM intelligence.reviews WHERE suggestion_id=%s AND decision='approve'", (suggestion_id,)).fetchone():
                raise ApplicationStateError("Approval is required", code="application_not_approved")
            connection.execute("UPDATE intelligence.change_applications SET status='applied',external_change_ref=%s,effect_succeeded_at=COALESCE(effect_succeeded_at,now()),applied_at=now(),lease_until=NULL,error_code=NULL WHERE change_application_id=%s", (external_change_ref,application['change_application_id']))
            connection.execute("UPDATE intelligence.application_attempts SET finished_at=now(),outcome='reconciled' WHERE change_application_id=%s AND finished_at IS NULL", (application['change_application_id'],))
            connection.execute("INSERT INTO intelligence.application_attempts (attempt_id,change_application_id,actor,finished_at,outcome) VALUES (%s,%s,%s,now(),'reconciled')", (uuid4(),application['change_application_id'],actor))
            connection.execute("UPDATE intelligence.suggestions SET status='applied' WHERE suggestion_id=%s", (suggestion_id,))

    def get_application(self, suggestion_id: UUID) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute("SELECT *,COALESCE(lease_until>now(),false) AS lease_active FROM intelligence.change_applications WHERE suggestion_id=%s ORDER BY attempted_at DESC NULLS LAST LIMIT 1", (suggestion_id,)).fetchone()
            return _jsonable(dict(row)) if row else None

    def finish_application(self, suggestion_id: UUID, *, applied: bool, external_change_ref: str | None = None, error_code: str | None = None, claim_token: UUID | None = None, reconciled: bool = False) -> None:
        status = 'applied' if applied else 'failed'
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute("SELECT suggestion_id FROM intelligence.suggestions WHERE suggestion_id=%s FOR UPDATE", (suggestion_id,))
            row = connection.execute("UPDATE intelligence.change_applications SET status=%s,external_change_ref=COALESCE(%s,external_change_ref),error_code=%s,lease_until=NULL,applied_at=CASE WHEN %s THEN now() ELSE NULL END WHERE suggestion_id=%s AND claim_token IS NOT DISTINCT FROM %s AND status IN ('applying','failed') RETURNING change_application_id", (status,external_change_ref,error_code,applied,suggestion_id,claim_token)).fetchone()
            if row is None:
                raise ApplicationStateError("Application claim does not match", code="application_claim_lost")
            connection.execute("UPDATE intelligence.application_attempts SET finished_at=now(),outcome=%s,error_code=%s WHERE attempt_id=%s", ('reconciled' if reconciled else status,error_code,claim_token))
            connection.execute("UPDATE intelligence.suggestions SET status=%s WHERE suggestion_id=%s", (status,suggestion_id))



def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    for key, item in tuple(value.items()):
        if hasattr(item, "isoformat"):
            value[key] = item.isoformat()
        elif not isinstance(item, (str, int, float, bool, list, dict, type(None))):
            value[key] = str(item)
    return value
