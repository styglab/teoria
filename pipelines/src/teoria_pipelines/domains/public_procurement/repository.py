"""Audit recording shared by procurement repositories; no feature aggregation."""

from uuid import UUID

from teoria_pipelines.persistence.connection import connect

from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.persistence.postgres import PostgresStore


class ProcurementRunRepository(PostgresStore):
    """Record procurement counts in the existing pipeline run audit columns."""

    async def complete_run(self, execution_id: UUID, summary: LoadSummary) -> None:
        async with connect(self.database_url) as connection:
            await connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='completed', finished_at=now(), "
                "raw_record_count=%s, contract_count=%s, notice_count=%s, "
                "award_count=%s, opening_participant_count=%s, notice_outcome_count=%s "
                "WHERE execution_id=%s",
                (
                    summary.raw_records,
                    summary.contracts,
                    summary.notices,
                    summary.awards,
                    summary.opening_participants,
                    summary.notice_outcomes,
                    execution_id,
                ),
            )
