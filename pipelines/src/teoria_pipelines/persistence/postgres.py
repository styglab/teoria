from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from teoria_pipelines.models import CollectionWindow, LoadSummary, NormalizedBatch, RawProviderRecord


class PostgresStore:
    """Data DB writer. A new short-lived connection is used per task boundary."""

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
                "raw_record_count=%s, contract_count=%s WHERE execution_id=%s",
                (summary.raw_records, summary.contracts, execution_id),
            )

    def fail_run(self, execution_id: UUID, error_code: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='failed', finished_at=now(), error_code=%s "
                "WHERE execution_id=%s",
                (error_code, execution_id),
            )

    def save_raw_records(self, records: Iterable[RawProviderRecord]) -> int:
        values = list(records)
        if not values:
            return 0
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO ingestion.raw_provider_records "
                    "(raw_record_id, execution_id, connector_id, operation_id, window_start, window_end, "
                    "fetched_at, source_record_hash, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (execution_id, connector_id, operation_id, source_record_hash) DO NOTHING",
                    [
                        (record.raw_record_id, record.execution_id, record.connector_id,
                         record.operation_id, record.window.start, record.window.end,
                         record.fetched_at, record.source_record_hash, Jsonb(record.payload))
                        for record in values
                    ],
                )
        return len(values)

    def upsert_normalized(self, batch: NormalizedBatch) -> LoadSummary:
        with psycopg.connect(self.database_url) as connection:
            self._upsert_many(connection, "public_procurement.contracts", batch.contracts,
                              ("unified_contract_number",))
            self._upsert_many(connection, "public_procurement.public_organizations",
                              batch.organizations, ("organization_code",))
            self._upsert_many(connection, "public_procurement.contract_suppliers",
                              batch.suppliers, ("unified_contract_number", "supplier_sequence"))
            self._upsert_many(connection, "public_procurement.contract_demand_organizations",
                              batch.demand_organizations,
                              ("unified_contract_number", "demand_organization_sequence"))
        return LoadSummary(
            contracts=len(batch.contracts),
            suppliers=len(batch.suppliers),
            organizations=len(batch.organizations),
            demand_organizations=len(batch.demand_organizations),
        )

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
        update = ", ".join(f"{column}=EXCLUDED.{column}" for column in assignments)
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update}"
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
