from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.models import CollectionWindow, LoadSummary
from teoria_pipelines.tasks import (
    combine_extracted_batches,
    complete_pipeline_run,
    fail_pipeline_run,
    save_raw_records,
    start_pipeline_run,
)
from teoria_pipelines.tasks.pps_bid_notices import (
    NOTICE_OPERATIONS,
    BACKFILL_PIPELINE_ID,
    PIPELINE_ID,
    claim_bid_documents,
    combine_bid_notice_summary,
    determine_bid_notice_window,
    determine_bid_notice_backfill_windows,
    extract_bid_notice_enrichment,
    extract_bid_notice_operation,
    normalize_bid_notice_enrichment,
    normalize_bid_notices,
    omit_historical_bid_documents,
    process_bid_documents,
    claim_expired_bid_document_objects,
    purge_expired_bid_document_objects,
    purge_expired_eligibility_outputs,
    record_bid_document_purge,
    upsert_bid_notice_enrichment,
    upsert_bid_notices,
    update_bid_notice_checkpoint,
)


OPERATION_TASK_NAMES = {
    "list_construction_bid_notices": "공사 입찰공고 수집",
    "list_service_bid_notices": "용역 입찰공고 수집",
    "list_foreign_bid_notices": "외자 입찰공고 수집",
    "list_goods_bid_notices": "물품 입찰공고 수집",
    "list_other_bid_notices": "기타 입찰공고 수집",
}


@flow(name="나라장터 입찰공고 일별 구간 수집")
async def sync_pps_bid_notice_window(
    window: CollectionWindow,
    pipeline_root: str = "/app/pipelines",
    pipeline_id: str = PIPELINE_ID,
    checkpoint_cursor: date | None = None,
    include_documents: bool = True,
    enrichment_batch_size: int = 20,
) -> LoadSummary:
    if enrichment_batch_size < 1:
        raise ValueError("enrichment_batch_size must be positive")
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    started_execution_id = start_pipeline_run(execution_id, pipeline_id, window)
    try:
        batches = []
        previous = None
        for operation_id in NOTICE_OPERATIONS:
            previous = await extract_bid_notice_operation.with_options(
                name=OPERATION_TASK_NAMES[operation_id]
            )(started_execution_id, window, operation_id, pipeline_root, previous)
            batches.append(previous)
        notices = combine_extracted_batches(execution_id, window, batches, previous)
        raw_notice_count = save_raw_records(notices)
        normalized_notices = normalize_bid_notices(notices, raw_notice_count)
        if not include_documents:
            normalized_notices = omit_historical_bid_documents(normalized_notices)
        notice_load = upsert_bid_notices(normalized_notices)
        changed_notices = notice_load[1]

        raw_enrichment_counts = []
        enrichment_loads = []
        for start in range(0, len(changed_notices), enrichment_batch_size):
            notice_chunk = changed_notices[start:start + enrichment_batch_size]
            enrichment = await extract_bid_notice_enrichment.with_options(
                name=(
                    "공고번호별 면허·지역 수집 "
                    f"{start // enrichment_batch_size + 1}/"
                    f"{(len(changed_notices) + enrichment_batch_size - 1) // enrichment_batch_size}"
                )
            )(execution_id, window, notice_chunk, pipeline_root, notice_load)
            raw_enrichment_count = save_raw_records(enrichment)
            normalized_enrichment = normalize_bid_notice_enrichment(
                enrichment, raw_enrichment_count
            )
            enrichment_load = upsert_bid_notice_enrichment(
                normalized_enrichment, notice_chunk
            )
            raw_enrichment_counts.append(raw_enrichment_count)
            enrichment_loads.append(enrichment_load)
        summary = combine_bid_notice_summary(
            raw_notice_count, raw_enrichment_counts, notice_load, enrichment_loads
        )
        checkpointed = update_bid_notice_checkpoint(
            execution_id, checkpoint_cursor or window.end, summary, pipeline_id
        )
        return complete_pipeline_run(execution_id, checkpointed)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise


@flow(name="나라장터 입찰공고·참가제한 수집")
async def sync_pps_bid_notices(
    pipeline_root: str = "/app/pipelines",
    lookback_days: int = 1,
    pipeline_id: str = PIPELINE_ID,
    enrichment_batch_size: int = 20,
) -> LoadSummary:
    window = determine_bid_notice_window(lookback_days)
    return await sync_pps_bid_notice_window(
        window, pipeline_root, pipeline_id,
        enrichment_batch_size=enrichment_batch_size,
    )


@flow(name="나라장터 입찰공고 Backfill")
async def sync_pps_bid_notice_backfill(
    checkpoint_id: str,
    start_date: date,
    end_date: date,
    pipeline_root: str = "/app/pipelines",
    batch_days: int = 30,
    enrichment_batch_size: int = 20,
) -> list[LoadSummary]:
    windows = determine_bid_notice_backfill_windows(
        checkpoint_id, start_date, end_date, batch_days
    )
    return [
        await sync_pps_bid_notice_window(
            window,
            pipeline_root,
            checkpoint_id,
            window.end,
            include_documents=False,
            enrichment_batch_size=enrichment_batch_size,
        )
        for window in windows
    ]


@flow(name="나라장터 입찰공고 첨부파일 수집")
async def sync_pps_bid_documents(
    batch_size: int = 500,
    concurrency: int = 8,
) -> LoadSummary:
    documents = claim_bid_documents(batch_size)
    return await process_bid_documents(documents, concurrency)


@flow(name="나라장터 입찰공고 첨부파일 보존기간 삭제")
def purge_expired_pps_bid_documents(
    retention_days: int = 90,
    batch_size: int = 500,
) -> LoadSummary:
    purge_run_id = uuid4()
    started_at = datetime.now(timezone.utc)
    documents = claim_expired_bid_document_objects(retention_days, batch_size)
    document_result = purge_expired_bid_document_objects(documents)
    result = purge_expired_eligibility_outputs(
        retention_days, batch_size, document_result
    )
    return record_bid_document_purge(
        purge_run_id, retention_days, started_at, result
    )
