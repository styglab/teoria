from __future__ import annotations

from uuid import UUID

from prefect import task

from teoria_pipelines.domains.public_procurement.bid_notices.models import (
    BidNoticeKey,
    NormalizedBidNoticeBatch,
)
from teoria_pipelines.domains.public_procurement.bid_notices.normalization import (
    normalize_bid_notice_batch,
)
from teoria_pipelines.domains.public_procurement.bid_notices.resources import (
    VIZ_EXTRACTED,
    VIZ_NORMALIZED,
    VIZ_SUMMARY,
    _client,
    _store,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.models import CollectionWindow, ExtractedBatch


@task(name="보강 미처리 입찰공고 선점", viz_return_value=[])
async def claim_pending_bid_notice_enrichment(
    batch_size: int = 20,
    minimum_age_days: int = 7,
    lease_minutes: int = 60,
) -> list[dict]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return await _store().claim_pending_bid_notice_enrichment(
        batch_size, minimum_age_days, lease_minutes
    )


@task(name="공고번호별 면허·지역 수집", viz_return_value=VIZ_EXTRACTED)
async def extract_bid_notice_enrichment(
    execution_id: UUID,
    window: CollectionWindow,
    notices: list[BidNoticeKey],
    pipeline_root: str,
    notice_load: tuple[LoadSummary, list[BidNoticeKey]] | None = None,
) -> ExtractedBatch:
    del notice_load
    if not notices:
        return ExtractedBatch(execution_id=execution_id, window=window)
    store = _store()
    await store.begin_bid_notice_requirement_collection(notices, execution_id)
    try:
        result = await _client(pipeline_root).fetch_enrichment(
            execution_id, window, notices
        )
    except BaseException as exc:
        await store.fail_bid_notice_requirement_collection(
            notices, execution_id, type(exc).__name__
        )
        raise
    return result


@task(name="면허·지역 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_notice_enrichment(
    batch: ExtractedBatch, raw_count: int
) -> NormalizedBidNoticeBatch:
    del raw_count
    return normalize_bid_notice_batch(batch)


@task(
    name="면허·지역 Upsert",
    retries=2,
    retry_delay_seconds=5,
    viz_return_value=VIZ_SUMMARY,
)
async def upsert_bid_notice_enrichment(
    batch: NormalizedBidNoticeBatch,
    notices: list[BidNoticeKey],
    extracted: ExtractedBatch,
) -> LoadSummary:
    store = _store()
    result = await store.upsert_bid_notice_enrichment(batch, notices)
    await store.complete_bid_notice_requirement_collection(
        notices, extracted, extracted.execution_id
    )
    return result
