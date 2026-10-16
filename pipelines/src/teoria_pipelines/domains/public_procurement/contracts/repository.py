from uuid import UUID

import psycopg
from teoria_pipelines.persistence.connection import connect

from teoria_pipelines.domains.public_procurement.contracts.models import NormalizedBatch
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.domains.public_procurement.repository import (
    ProcurementRunRepository,
)
from teoria_pipelines.models import CollectionWindow


class ContractRepository(ProcurementRunRepository):
    """Contract persistence operations."""

    async def upsert_normalized(self, batch: NormalizedBatch) -> LoadSummary:
        async with connect(self.database_url) as connection:
            await self._upsert_many(
                connection,
                "public_procurement.contracts",
                batch.contracts,
                ("unified_contract_number",),
            )
            await self._upsert_many(
                connection,
                "public_procurement.public_organizations",
                batch.organizations,
                ("organization_code",),
            )
            await self._upsert_many(
                connection,
                "public_procurement.contract_suppliers",
                batch.suppliers,
                ("unified_contract_number", "supplier_sequence"),
            )
            await self._upsert_many(
                connection,
                "public_procurement.contract_demand_organizations",
                batch.demand_organizations,
                ("unified_contract_number", "demand_organization_sequence"),
            )
        return LoadSummary(
            contracts=len(batch.contracts),
            suppliers=len(batch.suppliers),
            organizations=len(batch.organizations),
            demand_organizations=len(batch.demand_organizations),
        )

    async def get_completed_operation(
        self, pipeline_id: str, window: CollectionWindow, operation_id: str
    ) -> LoadSummary | None:
        async with connect(self.database_url) as connection:
            row = await (
                await connection.execute(
                    "SELECT raw_record_count,contract_count,supplier_count,organization_count,"
                    "demand_organization_count FROM ingestion.pipeline_operation_progress "
                    "WHERE pipeline_id=%s AND window_start=%s AND window_end=%s AND operation_id=%s",
                    (pipeline_id, window.start, window.end, operation_id),
                )
            ).fetchone()
        if row is None:
            return None
        return LoadSummary(
            raw_records=row[0],
            contracts=row[1],
            suppliers=row[2],
            organizations=row[3],
            demand_organizations=row[4],
        )

    async def complete_operation(
        self,
        pipeline_id: str,
        window: CollectionWindow,
        operation_id: str,
        execution_id: UUID,
        summary: LoadSummary,
    ) -> None:
        async with connect(self.database_url) as connection:
            await connection.execute(
                "INSERT INTO ingestion.pipeline_operation_progress "
                "(pipeline_id,window_start,window_end,operation_id,execution_id,"
                "raw_record_count,contract_count,supplier_count,organization_count,"
                "demand_organization_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (pipeline_id,window_start,window_end,operation_id) DO UPDATE SET "
                "execution_id=EXCLUDED.execution_id,raw_record_count=EXCLUDED.raw_record_count,"
                "contract_count=EXCLUDED.contract_count,supplier_count=EXCLUDED.supplier_count,"
                "organization_count=EXCLUDED.organization_count,"
                "demand_organization_count=EXCLUDED.demand_organization_count,completed_at=now()",
                (
                    pipeline_id,
                    window.start,
                    window.end,
                    operation_id,
                    execution_id,
                    summary.raw_records,
                    summary.contracts,
                    summary.suppliers,
                    summary.organizations,
                    summary.demand_organizations,
                ),
            )

    async def enqueue_contract_event_ledger_refresh(
        self,
        batch: NormalizedBatch,
    ) -> int:
        field_codes = sorted(
            {
                str(item["procurement_classification_number"])
                for item in batch.contracts
                if item.get("procurement_classification_number")
            }
        )
        if not field_codes:
            return 0
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO ingestion.contract_event_ledger_refresh_queue(field_code) VALUES (%s) "
                    "ON CONFLICT(field_code) DO UPDATE SET requested_at=now(),last_error=NULL,"
                    "request_version=contract_event_ledger_refresh_queue.request_version+1",
                    [(code,) for code in field_codes],
                )
        return len(field_codes)

    async def refresh_contract_event_ledger(self, batch_size: int = 5) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        refreshed = 0
        async with connect(self.database_url, autocommit=True) as connection:
            rows = await (
                await connection.execute(
                    "SELECT field_code FROM ingestion.contract_event_ledger_refresh_queue "
                    "ORDER BY requested_at,field_code LIMIT %s",
                    (batch_size,),
                )
            ).fetchall()
            for (field_code,) in rows:
                request_version = None
                try:
                    async with connection.transaction():
                        # Serialize refresh workers without locking the queue row:
                        # ingestion can enqueue a newer version during the refresh.
                        acquired = (
                            await (
                                await connection.execute(
                                    "SELECT pg_try_advisory_xact_lock("
                                    "hashtext('teoria.contract_event_ledger'),hashtext(%s))",
                                    (field_code,),
                                )
                            ).fetchone()
                        )[0]
                        if not acquired:
                            continue
                        request = await (
                            await connection.execute(
                                "SELECT request_version FROM "
                                "ingestion.contract_event_ledger_refresh_queue WHERE field_code=%s",
                                (field_code,),
                            )
                        ).fetchone()
                        if request is None:
                            continue
                        request_version = request[0]
                        await connection.execute(
                            "SELECT public_procurement.refresh_contract_event_company_ledger(%s)",
                            (field_code,),
                        )
                        await connection.execute(
                            "DELETE FROM ingestion.contract_event_ledger_refresh_queue "
                            "WHERE field_code=%s AND request_version=%s",
                            (field_code, request_version),
                        )
                    refreshed += 1
                except psycopg.Error as exc:
                    # A concurrent enqueue owns its own retry state.
                    await connection.execute(
                        "UPDATE ingestion.contract_event_ledger_refresh_queue "
                        "SET attempts=attempts+1,last_error=%s,requested_at=now() "
                        "WHERE field_code=%s AND request_version=%s",
                        (type(exc).__name__, field_code, request_version),
                    )
        return refreshed

    async def refresh_procurement_entity_search_index(self) -> None:
        async with connect(self.database_url, autocommit=True) as connection:
            await connection.execute(
                "SELECT public_procurement.refresh_procurement_entity_search_index()"
            )
