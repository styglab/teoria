from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from prefect import task

from teoria_pipelines.checkpoints import (
    resolve_backfill_windows,
    resolve_incremental_window,
)
from teoria_pipelines.domains.public_procurement.bid_notices.models import (
    BidNoticeKey,
    NormalizedBidNoticeBatch,
)
from teoria_pipelines.domains.public_procurement.bid_notices.normalization import (
    normalize_bid_notice_batch,
)
from teoria_pipelines.domains.public_procurement.bid_notices.resources import (
    PIPELINE_ID,
    SEOUL_TIMEZONE,
    VIZ_EXTRACTED,
    VIZ_NORMALIZED,
    VIZ_NOTICE_LOAD,
    VIZ_SUMMARY,
    VIZ_WINDOW,
    _client,
    _store,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.models import CollectionWindow, ExtractedBatch


@task(name="입찰공고 수집 구간 결정", viz_return_value=VIZ_WINDOW)
def determine_bid_notice_window(lookback_days: int = 1) -> CollectionWindow:
    today = datetime.now(SEOUL_TIMEZONE).date()
    return resolve_incremental_window(lookback_days=lookback_days, today=today)


@task(name="입찰공고 Backfill 구간 결정", viz_return_value=[VIZ_WINDOW])
def determine_bid_notice_backfill_windows(
    checkpoint_id: str,
    start_date: date,
    end_date: date,
    batch_days: int = 30,
) -> list[CollectionWindow]:
    checkpoint = _store().get_checkpoint(checkpoint_id)
    return resolve_backfill_windows(
        start_date=start_date,
        end_date=end_date,
        checkpoint=checkpoint,
        batch_days=batch_days,
        today=datetime.now(SEOUL_TIMEZONE).date(),
        reverse=True,
    )


@task(
    name="입찰공고 Operation 수집",
    retries=2,
    retry_delay_seconds=60,
    viz_return_value=VIZ_EXTRACTED,
)
async def extract_bid_notice_operation(
    execution_id: UUID,
    window: CollectionWindow,
    operation_id: str,
    pipeline_root: str,
    previous_operation: ExtractedBatch | None = None,
) -> ExtractedBatch:
    del previous_operation
    return await _client(pipeline_root).fetch_notice_operation(
        execution_id, window, operation_id
    )


@task(name="입찰공고 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_notices(
    batch: ExtractedBatch, raw_count: int
) -> NormalizedBidNoticeBatch:
    del raw_count
    return normalize_bid_notice_batch(batch)


@task(name="과거 공고 첨부파일 수집 제외", viz_return_value=VIZ_NORMALIZED)
def omit_historical_bid_documents(
    batch: NormalizedBidNoticeBatch,
) -> NormalizedBidNoticeBatch:
    batch.documents = []
    return batch


@task(
    name="입찰공고 Upsert",
    retries=2,
    retry_delay_seconds=5,
    viz_return_value=VIZ_NOTICE_LOAD,
)
def upsert_bid_notices(
    batch: NormalizedBidNoticeBatch,
) -> tuple[LoadSummary, list[BidNoticeKey]]:
    return _store().upsert_bid_notices(batch)


@task(name="입찰공고 적재결과 결합", viz_return_value=VIZ_SUMMARY)
def combine_bid_notice_summary(
    raw_notice_count: int,
    raw_enrichment_counts: list[int],
    notice_load: tuple[LoadSummary, list[BidNoticeKey]],
    enrichment_loads: list[LoadSummary],
) -> LoadSummary:
    notices, _ = notice_load
    return LoadSummary(
        raw_records=raw_notice_count + sum(raw_enrichment_counts),
        notices=notices.notices,
        documents=notices.documents,
        license_restrictions=sum(
            item.license_restrictions for item in enrichment_loads
        ),
        participation_regions=sum(
            item.participation_regions for item in enrichment_loads
        ),
    )


@task(name="입찰공고 Checkpoint 갱신", viz_return_value=VIZ_SUMMARY)
def update_bid_notice_checkpoint(
    execution_id: UUID,
    cursor_date: date,
    summary: LoadSummary,
    pipeline_id: str = PIPELINE_ID,
) -> LoadSummary:
    _store().update_checkpoint(pipeline_id, cursor_date, execution_id)
    return summary
