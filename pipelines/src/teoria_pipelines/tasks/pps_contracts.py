from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

from prefect import task
from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider

from teoria_pipelines.checkpoints import resolve_collection_window
from teoria_pipelines.connectors import PPSContractClient
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, LoadSummary, NormalizedBatch
from teoria_pipelines.normalization import normalize_contract_batch
from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings

PIPELINE_ID = "pps_contract_ingestion"
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


def _store() -> PostgresStore:
    settings = bootstrap_pipeline_settings()
    return PostgresStore(settings.data_database_url or "")


@task(name="수집 구간 결정", viz_return_value=VIZ_WINDOW)
def determine_collection_window(start_date: date | None, end_date: date | None,
                                overlap_days: int = 2) -> CollectionWindow:
    checkpoint = _store().get_checkpoint(PIPELINE_ID)
    return resolve_collection_window(
        requested_start=start_date,
        requested_end=end_date,
        checkpoint=checkpoint,
        overlap_days=overlap_days,
    )


@task(name="수집 실행 시작", viz_return_value=VIZ_EXECUTION_ID)
def start_pipeline_run(execution_id: UUID, window: CollectionWindow) -> UUID:
    _store().start_run(execution_id, PIPELINE_ID, window)
    return execution_id


@task(name="나라장터 Operation 수집", retries=3, retry_delay_seconds=[5, 15, 30],
      viz_return_value=VIZ_EXTRACTED)
async def extract_contract_operation(execution_id: UUID, window: CollectionWindow,
                                     operation_id: str,
                                     pipeline_root: str = "/app/pipelines",
                                     previous_operation: ExtractedBatch | None = None) -> ExtractedBatch:
    del previous_operation  # makes the provider-safe sequential order visible in Prefect
    settings = bootstrap_pipeline_settings()
    client = PPSContractClient.from_pipeline_root(
        Path(pipeline_root),
        executor=ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            secret_provider=EnvironmentSecretProvider(),
        ),
    )
    return await client.fetch_operation(execution_id, window, operation_id)


@task(name="Operation 응답 결합", viz_return_value=VIZ_EXTRACTED)
def combine_extracted_batches(execution_id: UUID, window: CollectionWindow,
                              batches: list[ExtractedBatch],
                              last_operation: ExtractedBatch) -> ExtractedBatch:
    del last_operation  # preserves the final Operation-to-merge edge in visualization
    return ExtractedBatch(
        execution_id=execution_id,
        window=window,
        records=[record for batch in batches for record in batch.records],
        pages=sum(batch.pages for batch in batches),
    )


@task(name="Raw 응답 저장", retries=2, retry_delay_seconds=5, viz_return_value=0)
def save_raw_records(batch: ExtractedBatch) -> int:
    return _store().save_raw_records(batch.records)


@task(name="계약정보 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_contracts(batch: ExtractedBatch, raw_record_count: int) -> NormalizedBatch:
    del raw_record_count  # establishes the Raw-save dependency in the Prefect graph
    return normalize_contract_batch(batch)


@task(name="정규 테이블 Upsert", retries=2, retry_delay_seconds=5,
      viz_return_value=VIZ_SUMMARY)
def upsert_contracts(batch: NormalizedBatch) -> LoadSummary:
    return _store().upsert_normalized(batch)


@task(name="Checkpoint 갱신", viz_return_value=VIZ_SUMMARY)
def update_checkpoint(execution_id: UUID, window: CollectionWindow,
                      raw_record_count: int, load_summary: LoadSummary) -> LoadSummary:
    _store().update_checkpoint(PIPELINE_ID, window.end, execution_id)
    return LoadSummary(
        raw_records=raw_record_count,
        contracts=load_summary.contracts,
        suppliers=load_summary.suppliers,
        organizations=load_summary.organizations,
        demand_organizations=load_summary.demand_organizations,
    )


@task(name="수집 실행 완료", viz_return_value=VIZ_SUMMARY)
def complete_pipeline_run(execution_id: UUID, summary: LoadSummary) -> LoadSummary:
    _store().complete_run(execution_id, summary)
    return summary


@task(name="수집 실행 실패 기록")
def fail_pipeline_run(execution_id: UUID, error_code: str) -> None:
    _store().fail_run(execution_id, error_code)
