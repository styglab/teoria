from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

from prefect import task
from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.secrets import EnvironmentSecretProvider

from teoria_pipelines.domains.public_procurement.calendar import procurement_today
from teoria_pipelines.checkpoints import resolve_collection_window
from teoria_pipelines.domains.public_procurement.contracts.client import (
    PPSContractClient,
)
from teoria_pipelines.domains.public_procurement.contracts.models import NormalizedBatch
from teoria_pipelines.domains.public_procurement.contracts.normalization import (
    normalize_contract_batch,
)
from teoria_pipelines.domains.public_procurement.contracts.resources import _store
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.domains.public_procurement.provider_response import (
    ConnectorResponseError,
)
from teoria_pipelines.models import CollectionWindow, ExtractedBatch
from teoria_pipelines.settings import bootstrap_pipeline_settings

PIPELINE_ID = "pps_contract_ingestion"

INCREMENTAL_PIPELINE_ID = "pps_contract_incremental"

BACKFILL_PIPELINE_ID = "pps_contract_backfill_2021_2026"


OPERATIONS = [
    "list_goods_contracts",
    "list_construction_contracts",
    "list_service_contracts",
    "list_foreign_procurement_contracts",
]

VIZ_EXECUTION_ID = UUID(int=0)

VIZ_WINDOW = CollectionWindow(date(2026, 1, 1), date(2026, 1, 1))

VIZ_EXTRACTED = ExtractedBatch(execution_id=VIZ_EXECUTION_ID, window=VIZ_WINDOW)

VIZ_NORMALIZED = NormalizedBatch()

VIZ_SUMMARY = LoadSummary()


@task(name="수집 구간 결정", viz_return_value=VIZ_WINDOW)
async def determine_collection_window(
    start_date: date | None, end_date: date | None, overlap_days: int = 2
) -> CollectionWindow:
    checkpoint = await _store().get_checkpoint(PIPELINE_ID)
    return resolve_collection_window(
        requested_start=start_date,
        requested_end=end_date,
        checkpoint=checkpoint,
        overlap_days=overlap_days,
        today=procurement_today(),
    )


@task(
    name="나라장터 Operation 수집",
    retries=1,
    retry_delay_seconds=300,
    viz_return_value=VIZ_EXTRACTED,
)
async def extract_contract_operation(
    execution_id: UUID,
    window: CollectionWindow,
    operation_id: str,
    pipeline_root: str = "/app/pipelines",
    previous_operation: ExtractedBatch | None = None,
    page_sizes: tuple[int, ...] = (100,),
    provider_error_max_attempts: int | None = None,
) -> ExtractedBatch:
    del (
        previous_operation
    )  # makes the provider-safe sequential order visible in Prefect
    settings = bootstrap_pipeline_settings()
    last_error: ConnectorResponseError | None = None
    for page_size in page_sizes:
        client = PPSContractClient.from_pipeline_root(
            Path(pipeline_root),
            executor=ProviderExecutor(
                timeout_seconds=settings.source_timeout_seconds,
                max_attempts=settings.source_max_attempts,
                backoff_seconds=settings.source_retry_backoff_seconds,
                secret_provider=EnvironmentSecretProvider(),
            ),
            page_size=page_size,
            requests_per_second=settings.contract_requests_per_second,
            provider_error_max_attempts=(
                provider_error_max_attempts or settings.source_max_attempts
            ),
            provider_error_backoff_seconds=settings.source_retry_backoff_seconds,
        )
        try:
            return await client.fetch_operation(execution_id, window, operation_id)
        except ConnectorResponseError as exc:
            last_error = exc
            if "provider_error code=99" not in str(exc):
                raise
    assert last_error is not None
    raise last_error


@task(name="Backfill 결손 기록", viz_return_value=None)
async def record_backfill_gap(
    pipeline_id: str, window: CollectionWindow, operation_id: str, error_code: str
) -> None:
    await _store().record_backfill_gap(pipeline_id, window, operation_id, error_code)


@task(name="Backfill 결손 재시도 대상 선택", viz_return_value=[])
async def claim_backfill_gaps(
    pipeline_id: str, batch_size: int = 1, retry_days: int = 1, max_attempts: int = 15
) -> list[dict]:
    return await _store().claim_backfill_gaps(
        pipeline_id, batch_size, retry_days, max_attempts
    )


@task(name="Backfill 결손 해결", viz_return_value=None)
async def resolve_backfill_gap(
    pipeline_id: str, window: CollectionWindow, operation_id: str
) -> None:
    await _store().resolve_backfill_gap(pipeline_id, window, operation_id)


@task(name="계약정보 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_contracts(
    batch: ExtractedBatch, raw_record_count: int
) -> NormalizedBatch:
    del raw_record_count  # establishes the Raw-save dependency in the Prefect graph
    return normalize_contract_batch(batch)


@task(
    name="정규 테이블 Upsert",
    retries=2,
    retry_delay_seconds=5,
    viz_return_value=VIZ_SUMMARY,
)
async def upsert_contracts(batch: NormalizedBatch) -> LoadSummary:
    return await _store().upsert_normalized(batch)


@task(name="계약 분야 집계 갱신 예약", viz_return_value=0)
async def enqueue_contract_event_ledger_refresh(
    batch: NormalizedBatch,
    load_summary: LoadSummary,
) -> int:
    del load_summary
    return await _store().enqueue_contract_event_ledger_refresh(batch)


@task(
    name="계약 사건 사전집계 갱신",
    retries=1,
    retry_delay_seconds=60,
    viz_return_value=0,
)
async def refresh_contract_event_ledger(batch_size: int = 5) -> int:
    return await _store().refresh_contract_event_ledger(batch_size)


@task(
    name="조달 개체 검색 인덱스 갱신",
    retries=1,
    retry_delay_seconds=60,
    viz_return_value=None,
)
async def refresh_procurement_entity_search_index() -> None:
    await _store().refresh_procurement_entity_search_index()


@task(name="완료 Operation 확인", viz_return_value=None)
async def get_completed_operation(
    pipeline_id: str, window: CollectionWindow, operation_id: str
) -> LoadSummary | None:
    return await _store().get_completed_operation(pipeline_id, window, operation_id)


@task(name="Operation 완료 기록", viz_return_value=VIZ_SUMMARY)
async def complete_operation(
    pipeline_id: str,
    window: CollectionWindow,
    operation_id: str,
    execution_id: UUID,
    raw_record_count: int,
    load_summary: LoadSummary,
) -> LoadSummary:
    summary = LoadSummary(
        raw_records=raw_record_count,
        contracts=load_summary.contracts,
        suppliers=load_summary.suppliers,
        organizations=load_summary.organizations,
        demand_organizations=load_summary.demand_organizations,
    )
    await _store().complete_operation(
        pipeline_id, window, operation_id, execution_id, summary
    )
    return summary
