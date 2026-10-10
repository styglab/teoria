from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import re
from psycopg.types.json import Jsonb

from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    LoadSummary,
    NormalizedBatch,
    NormalizedBidResultBatch,
    NormalizedBidNoticeBatch,
    RawProviderRecord,
)

from teoria_pipelines.persistence.postgres_store.support import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    _validate_industry_snapshot,
    eligibility_requires_review,
)


class BasePostgresStore:
    """base persistence operations."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("TEORIA_PIPELINE_DATA_DATABASE_URL is required")
        self.database_url = database_url

    def apply_migrations(self, migration_root: Path) -> list[str]:
        applied: list[str] = []
        with psycopg.connect(self.database_url) as connection:
            connection.execute("CREATE SCHEMA IF NOT EXISTS ingestion")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS ingestion.schema_migrations "
                "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            existing = {
                row[0]
                for row in connection.execute("SELECT version FROM ingestion.schema_migrations")
            }
            for path in sorted(migration_root.glob("*.sql")):
                if path.name in existing:
                    continue
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO ingestion.schema_migrations (version) VALUES (%s)",
                    (path.name,),
                )
                applied.append(path.name)
        return applied

    def start_run(self, execution_id: UUID, pipeline_id: str, window: CollectionWindow,
                  started_at: datetime | None = None) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_runs "
                "(execution_id, pipeline_id, window_start, window_end, started_at, status) "
                "VALUES (%s, %s, %s, %s, %s, 'running')",
                (execution_id, pipeline_id, window.start, window.end,
                 started_at or datetime.now(timezone.utc)),
            )

    def complete_run(self, execution_id: UUID, summary: LoadSummary) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='completed', finished_at=now(), "
                "raw_record_count=%s, contract_count=%s, notice_count=%s, document_count=%s, "
                "award_count=%s, opening_participant_count=%s, notice_outcome_count=%s "
                "WHERE execution_id=%s",
                (summary.raw_records, summary.contracts, summary.notices,
                 summary.documents, summary.awards, summary.opening_participants,
                 summary.notice_outcomes, execution_id),
            )

    def fail_run(self, execution_id: UUID, error_code: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='failed', finished_at=now(), error_code=%s "
                "WHERE execution_id=%s",
                (error_code, execution_id),
            )

    def list_running_runs(self) -> list[dict[str, Any]]:
        """Return durable runs that may have been orphaned with a worker process."""
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT execution_id,pipeline_id,window_start,window_end,started_at "
                "FROM ingestion.pipeline_runs WHERE status='running' ORDER BY started_at"
            ).fetchall()
        return [
            {
                "execution_id": row[0],
                "pipeline_id": row[1],
                "window_start": row[2],
                "window_end": row[3],
                "started_at": row[4],
            }
            for row in rows
        ]

    def get_completed_operation(self, pipeline_id: str, window: CollectionWindow,
                                operation_id: str) -> LoadSummary | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT raw_record_count,contract_count,supplier_count,organization_count,"
                "demand_organization_count FROM ingestion.pipeline_operation_progress "
                "WHERE pipeline_id=%s AND window_start=%s AND window_end=%s AND operation_id=%s",
                (pipeline_id, window.start, window.end, operation_id),
            ).fetchone()
        if row is None:
            return None
        return LoadSummary(
            raw_records=row[0], contracts=row[1], suppliers=row[2],
            organizations=row[3], demand_organizations=row[4],
        )

    def complete_operation(self, pipeline_id: str, window: CollectionWindow,
                           operation_id: str, execution_id: UUID,
                           summary: LoadSummary) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_operation_progress "
                "(pipeline_id,window_start,window_end,operation_id,execution_id,"
                "raw_record_count,contract_count,supplier_count,organization_count,"
                "demand_organization_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (pipeline_id,window_start,window_end,operation_id) DO UPDATE SET "
                "execution_id=EXCLUDED.execution_id,raw_record_count=EXCLUDED.raw_record_count,"
                "contract_count=EXCLUDED.contract_count,supplier_count=EXCLUDED.supplier_count,"
                "organization_count=EXCLUDED.organization_count,"
                "demand_organization_count=EXCLUDED.demand_organization_count,completed_at=now()",
                (pipeline_id, window.start, window.end, operation_id, execution_id,
                 summary.raw_records, summary.contracts, summary.suppliers,
                 summary.organizations, summary.demand_organizations),
            )

    def record_backfill_gap(self, pipeline_id: str, window: CollectionWindow,
                            operation_id: str, error_code: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_backfill_gaps "
                "(pipeline_id,window_start,window_end,operation_id,error_code) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT "
                "(pipeline_id,window_start,window_end,operation_id) DO UPDATE SET "
                "error_code=EXCLUDED.error_code,next_retry_at=now(),resolved_at=NULL,updated_at=now()",
                (pipeline_id, window.start, window.end, operation_id, error_code[:500]),
            )

    def claim_backfill_gaps(self, pipeline_id: str, limit: int,
                            retry_days: int = 1,
                            max_attempts: int = 15) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "WITH candidates AS (SELECT pipeline_id,window_start,window_end,operation_id "
                "FROM ingestion.pipeline_backfill_gaps WHERE pipeline_id=%s "
                "AND resolved_at IS NULL AND attempts<%s AND next_retry_at<=now() "
                "ORDER BY window_start DESC "
                "FOR UPDATE SKIP LOCKED LIMIT %s) UPDATE ingestion.pipeline_backfill_gaps g "
                "SET attempts=g.attempts+1,next_retry_at=now()+(%s * interval '1 day'),updated_at=now() "
                "FROM candidates c WHERE g.pipeline_id=c.pipeline_id AND g.window_start=c.window_start "
                "AND g.window_end=c.window_end AND g.operation_id=c.operation_id "
                "RETURNING g.pipeline_id,g.window_start,g.window_end,g.operation_id,g.attempts",
                (pipeline_id, max_attempts, limit, retry_days),
            ).fetchall()
        keys = ("pipeline_id", "window_start", "window_end", "operation_id", "attempts")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def resolve_backfill_gap(self, pipeline_id: str, window: CollectionWindow,
                             operation_id: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_backfill_gaps SET resolved_at=now(),updated_at=now() "
                "WHERE pipeline_id=%s AND window_start=%s AND window_end=%s AND operation_id=%s",
                (pipeline_id, window.start, window.end, operation_id),
            )

    def save_raw_records(self, records: Iterable[RawProviderRecord]) -> int:
        values = list(records)
        if not values:
            return 0
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO ingestion.raw_provider_payloads "
                    "(connector_id, operation_id, source_record_hash, payload, "
                    "first_seen_at, last_seen_at) VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (connector_id, operation_id, source_record_hash) DO UPDATE "
                    "SET last_seen_at=GREATEST(raw_provider_payloads.last_seen_at, "
                    "EXCLUDED.last_seen_at)",
                    [
                        (record.connector_id, record.operation_id,
                         record.source_record_hash, Jsonb(record.payload),
                         record.fetched_at, record.fetched_at)
                        for record in values
                    ],
                )
                cursor.executemany(
                    "INSERT INTO ingestion.raw_provider_observations "
                    "(observation_id, execution_id, connector_id, operation_id, "
                    "source_record_hash, window_start, window_end, fetched_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (execution_id, connector_id, operation_id, "
                    "source_record_hash) DO NOTHING",
                    [
                        (record.raw_record_id, record.execution_id,
                         record.connector_id, record.operation_id,
                         record.source_record_hash, record.window.start,
                         record.window.end, record.fetched_at)
                        for record in values
                    ],
                )
                inserted = cursor.rowcount
        return inserted

    @staticmethod
    def _upsert_many(connection: Any, table: str, rows: list[dict[str, Any]],
                     keys: tuple[str, ...]) -> None:
        if not rows:
            return
        columns = tuple(rows[0])
        if any(tuple(row) != columns for row in rows):
            raise ValueError(f"all rows for {table} must have identical columns")
        assignments = [column for column in columns if column not in keys]
        placeholders = ", ".join(f"%({column})s" for column in columns)
        conflict = ", ".join(keys)
        update = ", ".join(
            [*(f"{column}=EXCLUDED.{column}" for column in assignments), "updated_at=now()"]
        )
        changed = " OR ".join(
            f"{table}.{column} IS DISTINCT FROM EXCLUDED.{column}"
            for column in assignments
        )
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update} WHERE {changed}"
        )
        with connection.cursor() as cursor:
            cursor.executemany(statement, rows)

    def get_checkpoint(self, pipeline_id: str) -> date | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT cursor_date FROM ingestion.pipeline_checkpoints WHERE pipeline_id=%s",
                (pipeline_id,),
            ).fetchone()
        return row[0] if row else None

    def update_checkpoint(self, pipeline_id: str, cursor_date: date,
                          execution_id: UUID) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_checkpoints "
                "(pipeline_id, cursor_date, execution_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (pipeline_id) DO UPDATE SET cursor_date=EXCLUDED.cursor_date, "
                "execution_id=EXCLUDED.execution_id, updated_at=now()",
                (pipeline_id, cursor_date, execution_id),
            )
