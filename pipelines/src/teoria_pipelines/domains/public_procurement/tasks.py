"""Prefect boundary for procurement execution audit recording."""

from uuid import UUID

from prefect import task

from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.domains.public_procurement.repository import (
    ProcurementRunRepository,
)
from teoria_pipelines.settings import bootstrap_pipeline_settings


@task(name="수집 실행 완료", viz_return_value=LoadSummary())
async def complete_pipeline_run(
    execution_id: UUID, summary: LoadSummary
) -> LoadSummary:
    repository = ProcurementRunRepository(
        bootstrap_pipeline_settings().data_database_url or ""
    )
    await repository.complete_run(execution_id, summary)
    return summary
