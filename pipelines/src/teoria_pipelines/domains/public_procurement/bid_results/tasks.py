from __future__ import annotations

from teoria_pipelines.domains.public_procurement.calendar import procurement_today

from datetime import date
from pathlib import Path
from uuid import UUID

from prefect import task
from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.secrets import EnvironmentSecretProvider

from teoria_pipelines.domains.public_procurement.bid_results.client import (
    PPSBidResultClient,
)
from teoria_pipelines.domains.public_procurement.bid_results.models import (
    NormalizedBidResultBatch,
    NoticeOutcomeResultBatch,
    OpeningResultBatch,
)
from teoria_pipelines.domains.public_procurement.bid_results.normalization import (
    normalize_bid_result_batch,
)
from teoria_pipelines.domains.public_procurement.bid_results.repository import (
    BidResultRepository,
)
from teoria_pipelines.domains.public_procurement.bid_results.selection import (
    select_participants,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.models import CollectionWindow, ExtractedBatch
from teoria_pipelines.settings import bootstrap_pipeline_settings

PIPELINE_ID = "pps_bid_result_ingestion"
INCREMENTAL_PIPELINE_ID = "pps_bid_result_incremental"
BACKFILL_PIPELINE_ID = "pps_bid_result_backfill_5y"
from teoria_pipelines.domains.public_procurement.bid_results.client import (
    AWARD_OPERATIONS as AWARD_OPERATIONS,
)

VIZ_EXTRACTED = ExtractedBatch(
    execution_id=UUID(int=0),
    window=CollectionWindow(date(2026, 1, 1), date(2026, 1, 1)),
)
VIZ_NORMALIZED = NormalizedBidResultBatch()
VIZ_SUMMARY = LoadSummary()


def _store() -> BidResultRepository:
    settings = bootstrap_pipeline_settings()
    return BidResultRepository(settings.data_database_url or "")


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
        opening_concurrency=settings.bid_opening_concurrency,
        opening_requests_per_second=settings.bid_opening_requests_per_second,
        opening_request_timeout_seconds=settings.bid_opening_request_timeout_seconds,
    )


@task(name="개찰 보강 대상 등록")
async def enqueue_opening_enrichment(awards: ExtractedBatch, queue_class: str) -> int:
    return await _store().enqueue_bid_opening_enrichment(awards.records, queue_class)


@task(name="개찰 보강 대상 선점", viz_return_value=VIZ_EXTRACTED)
async def claim_opening_enrichment(
    execution_id: UUID, queue_mode: str, batch_size: int = 20, lease_minutes: int = 15
) -> ExtractedBatch:
    records = await _store().claim_bid_opening_enrichment(
        execution_id, queue_mode, batch_size, lease_minutes
    )
    today = procurement_today()
    return ExtractedBatch(execution_id, CollectionWindow(today, today), records)


@task(name="개찰 보강 상태 저장")
async def finish_opening_enrichment(result: OpeningResultBatch) -> None:
    await _store().finish_bid_opening_enrichment(
        result.successful_awards.records, result.failed_awards.records
    )


@task(
    name="낙찰 목록 Operation 수집",
    retries=1,
    retry_delay_seconds=300,
    viz_return_value=VIZ_EXTRACTED,
)
async def extract_bid_award_operation(
    execution_id: UUID,
    window: CollectionWindow,
    operation_id: str,
    pipeline_root: str,
    previous_operation: ExtractedBatch | None = None,
) -> ExtractedBatch:
    del previous_operation
    return await _client(pipeline_root).fetch_award_operation(
        execution_id, window, operation_id
    )


@task(
    name="공고별 개찰 참여업체 수집",
    retries=1,
    retry_delay_seconds=300,
    viz_return_value=VIZ_EXTRACTED,
)
async def extract_opening_participants(
    execution_id: UUID,
    window: CollectionWindow,
    awards: ExtractedBatch,
    pipeline_root: str,
) -> OpeningResultBatch:
    return await _client(pipeline_root).fetch_opening_results(
        execution_id, window, awards.records
    )


@task(name="유찰 상태 미확인 공고 선별", viz_return_value=VIZ_EXTRACTED)
async def claim_notice_outcome_candidates(
    execution_id: UUID,
    batch_size: int = 100,
) -> ExtractedBatch:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    today = procurement_today()
    return ExtractedBatch(
        execution_id,
        CollectionWindow(today, today),
        (await _store().select_pending_bid_notice_outcomes(execution_id, batch_size)),
    )


@task(name="공고별 유찰 결과 수집", retries=1, retry_delay_seconds=300)
async def extract_failing_results(
    execution_id: UUID,
    window: CollectionWindow,
    notices: ExtractedBatch,
    pipeline_root: str,
) -> NoticeOutcomeResultBatch:
    return await _client(pipeline_root).fetch_failing_results(
        execution_id,
        window,
        notices.records,
    )


@task(name="유찰 조회 완료상태 저장")
async def mark_notice_outcomes_checked(result: NoticeOutcomeResultBatch) -> int:
    return await _store().mark_bid_notice_outcomes_checked(
        result.successful_notices.records,
        result.outcomes.records,
    )


@task(name="낙찰정보 응답 결합", viz_return_value=VIZ_EXTRACTED)
def combine_bid_result_batches(
    execution_id: UUID,
    window: CollectionWindow,
    batches: list[ExtractedBatch],
    opening_batch: ExtractedBatch,
) -> ExtractedBatch:
    return ExtractedBatch(
        execution_id=execution_id,
        window=window,
        records=[
            record for batch in [*batches, opening_batch] for record in batch.records
        ],
        pages=sum(batch.pages for batch in [*batches, opening_batch]),
    )


@task(name="개찰 미수집·변경 공고 선별", viz_return_value=VIZ_EXTRACTED)
async def select_pending_opening_awards(awards: ExtractedBatch) -> ExtractedBatch:
    return ExtractedBatch(
        execution_id=awards.execution_id,
        window=awards.window,
        records=(await _store().select_bid_awards_for_opening(awards.records)),
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
            records=awards.records[offset : offset + chunk_size],
        )
        for offset in range(0, len(awards.records), chunk_size)
    ]


@task(name="상위 경쟁 참여업체 선별", viz_return_value=VIZ_EXTRACTED)
def select_competitive_opening_participants(
    awards: ExtractedBatch, openings: ExtractedBatch, maximum_rank: int = 10
) -> ExtractedBatch:
    """Retain only top-ranked participants and the recorded winner.

    Mere participation is intentionally not treated as a relationship signal.
    Rank-less records are retained only when their business number matches the
    final award record.
    """
    return select_participants(awards, openings, maximum_rank)


@task(name="낙찰정보 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_results(
    batch: ExtractedBatch, raw_record_count: int
) -> NormalizedBidResultBatch:
    del raw_record_count
    return normalize_bid_result_batch(batch)


@task(
    name="낙찰정보 정규 테이블 Upsert",
    retries=2,
    retry_delay_seconds=5,
    viz_return_value=VIZ_SUMMARY,
)
async def upsert_bid_results(batch: NormalizedBidResultBatch) -> LoadSummary:
    return await _store().upsert_bid_results(batch)


@task(
    name="개찰 참여업체 청크 교체 저장",
    retries=2,
    retry_delay_seconds=5,
    viz_return_value=VIZ_SUMMARY,
)
async def replace_opening_participants(
    awards: ExtractedBatch, batch: NormalizedBidResultBatch
) -> LoadSummary:
    return await _store().replace_bid_opening_participants(awards.records, batch)


@task(name="개찰 수집 완료상태 저장")
async def mark_opening_awards_checked(
    awards: ExtractedBatch, openings: ExtractedBatch, loaded: LoadSummary
) -> int:
    del loaded
    return await _store().mark_bid_openings_checked(
        awards.records, openings.records, awards.execution_id
    )


@task(name="낙찰정보 적재 결과 결합", viz_return_value=VIZ_SUMMARY)
def combine_bid_result_summaries(
    award_raw_count: int,
    award_loaded: LoadSummary,
    opening_raw_counts: list[int],
    opening_loaded: list[LoadSummary],
    checked_counts: list[int],
) -> LoadSummary:
    del checked_counts
    return LoadSummary(
        raw_records=award_raw_count + sum(opening_raw_counts),
        awards=award_loaded.awards,
        opening_participants=sum(item.opening_participants for item in opening_loaded),
    )
