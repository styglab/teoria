from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.models import LoadSummary
from teoria_pipelines.tasks import (
    combine_extracted_batches,
    complete_pipeline_run,
    fail_pipeline_run,
    save_raw_records,
    start_pipeline_run,
)
from teoria_pipelines.tasks.pps_bid_notices import (
    NOTICE_OPERATIONS,
    PIPELINE_ID,
    claim_bid_documents,
    combine_bid_notice_summary,
    determine_bid_notice_window,
    extract_bid_notice_enrichment,
    extract_bid_notice_operation,
    normalize_bid_notice_enrichment,
    normalize_bid_notices,
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


@flow(name="나라장터 입찰공고·참가제한 수집")
async def sync_pps_bid_notices(
    pipeline_root: str = "/app/pipelines",
    lookback_days: int = 1,
) -> LoadSummary:
    window = determine_bid_notice_window(lookback_days)
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    started_execution_id = start_pipeline_run(execution_id, PIPELINE_ID, window)
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
        notice_load = upsert_bid_notices(normalized_notices)
        changed_notices = notice_load[1]

        enrichment = await extract_bid_notice_enrichment(
            execution_id, window, changed_notices, pipeline_root, notice_load
        )
        raw_enrichment_count = save_raw_records(enrichment)
        normalized_enrichment = normalize_bid_notice_enrichment(
            enrichment, raw_enrichment_count
        )
        enrichment_load = upsert_bid_notice_enrichment(
            normalized_enrichment, changed_notices
        )
        summary = combine_bid_notice_summary(
            raw_notice_count, raw_enrichment_count, notice_load, enrichment_load
        )
        checkpointed = update_bid_notice_checkpoint(execution_id, window.end, summary)
        return complete_pipeline_run(execution_id, checkpointed)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise


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
