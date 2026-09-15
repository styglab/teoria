from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

from prefect import task
from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider

from teoria_pipelines.connectors import PPSBidResultClient
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, LoadSummary, NormalizedBidResultBatch
from teoria_pipelines.normalization import normalize_bid_result_batch
from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings


PIPELINE_ID = "pps_bid_result_ingestion"
INCREMENTAL_PIPELINE_ID = "pps_bid_result_incremental"
BACKFILL_PIPELINE_ID = "pps_bid_result_backfill_5y"
AWARD_OPERATIONS = [
    "list_goods_bid_awards",
    "list_construction_bid_awards",
    "list_service_bid_awards",
    "list_foreign_bid_awards",
]
VIZ_EXTRACTED = ExtractedBatch(
    execution_id=UUID(int=0), window=CollectionWindow(date(2026, 1, 1), date(2026, 1, 1))
)
VIZ_NORMALIZED = NormalizedBidResultBatch()
VIZ_SUMMARY = LoadSummary()


def _store() -> PostgresStore:
    settings = bootstrap_pipeline_settings()
    return PostgresStore(settings.data_database_url or "")


def _client(pipeline_root: str) -> PPSBidResultClient:
    settings = bootstrap_pipeline_settings()
    return PPSBidResultClient.from_pipeline_root(
        Path(pipeline_root),
        executor=ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            backoff_seconds=settings.source_retry_backoff_seconds,
            secret_provider=EnvironmentSecretProvider(),
        ),
    )


@task(name="낙찰 목록 Operation 수집", retries=1, retry_delay_seconds=300,
      viz_return_value=VIZ_EXTRACTED)
async def extract_bid_award_operation(execution_id: UUID, window: CollectionWindow,
                                      operation_id: str, pipeline_root: str,
                                      previous_operation: ExtractedBatch | None = None) -> ExtractedBatch:
    del previous_operation
    return await _client(pipeline_root).fetch_award_operation(execution_id, window, operation_id)


@task(name="공고별 개찰 참여업체 수집", retries=1, retry_delay_seconds=300,
      viz_return_value=VIZ_EXTRACTED)
async def extract_opening_participants(execution_id: UUID, window: CollectionWindow,
                                       awards: ExtractedBatch, pipeline_root: str) -> ExtractedBatch:
    return await _client(pipeline_root).fetch_opening_results(
        execution_id, window, awards.records
    )


@task(name="낙찰정보 응답 결합", viz_return_value=VIZ_EXTRACTED)
def combine_bid_result_batches(execution_id: UUID, window: CollectionWindow,
                               batches: list[ExtractedBatch],
                               opening_batch: ExtractedBatch) -> ExtractedBatch:
    return ExtractedBatch(
        execution_id=execution_id,
        window=window,
        records=[record for batch in [*batches, opening_batch] for record in batch.records],
        pages=sum(batch.pages for batch in [*batches, opening_batch]),
    )


@task(name="개찰 미수집·변경 공고 선별", viz_return_value=VIZ_EXTRACTED)
def select_pending_opening_awards(awards: ExtractedBatch) -> ExtractedBatch:
    return ExtractedBatch(
        execution_id=awards.execution_id,
        window=awards.window,
        records=_store().select_bid_awards_for_opening(awards.records),
    )


@task(name="개찰 대상 청크 분할")
def split_opening_award_chunks(
    awards: ExtractedBatch, chunk_size: int = 100
) -> list[ExtractedBatch]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    return [
        ExtractedBatch(
            execution_id=awards.execution_id,
            window=awards.window,
            records=awards.records[offset:offset + chunk_size],
        )
        for offset in range(0, len(awards.records), chunk_size)
    ]


@task(name="낙찰정보 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_results(batch: ExtractedBatch, raw_record_count: int) -> NormalizedBidResultBatch:
    del raw_record_count
    return normalize_bid_result_batch(batch)


@task(name="낙찰정보 정규 테이블 Upsert", retries=2, retry_delay_seconds=5,
      viz_return_value=VIZ_SUMMARY)
def upsert_bid_results(batch: NormalizedBidResultBatch) -> LoadSummary:
    return _store().upsert_bid_results(batch)


@task(name="개찰 참여업체 청크 교체 저장", retries=2, retry_delay_seconds=5,
      viz_return_value=VIZ_SUMMARY)
def replace_opening_participants(
    awards: ExtractedBatch, batch: NormalizedBidResultBatch
) -> LoadSummary:
    return _store().replace_bid_opening_participants(awards.records, batch)


@task(name="개찰 수집 완료상태 저장")
def mark_opening_awards_checked(
    awards: ExtractedBatch, openings: ExtractedBatch, loaded: LoadSummary
) -> int:
    del loaded
    return _store().mark_bid_openings_checked(
        awards.records, openings.records, awards.execution_id
    )


@task(name="낙찰정보 적재 결과 결합", viz_return_value=VIZ_SUMMARY)
def combine_bid_result_summaries(
    award_raw_count: int, award_loaded: LoadSummary,
    opening_raw_counts: list[int], opening_loaded: list[LoadSummary],
    checked_counts: list[int],
) -> LoadSummary:
    del checked_counts
    return LoadSummary(
        raw_records=award_raw_count + sum(opening_raw_counts),
        awards=award_loaded.awards,
        opening_participants=sum(item.opening_participants for item in opening_loaded),
    )
