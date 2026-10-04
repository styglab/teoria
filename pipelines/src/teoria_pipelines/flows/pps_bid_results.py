from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.checkpoints import split_windows
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, LoadSummary
from teoria_pipelines.tasks import (
    complete_pipeline_run,
    fail_pipeline_run,
    start_pipeline_run,
    update_checkpoint,
)
from teoria_pipelines.tasks.pps_bid_results import (
    AWARD_OPERATIONS,
    BACKFILL_PIPELINE_ID,
    INCREMENTAL_PIPELINE_ID,
    PIPELINE_ID,
    combine_bid_result_batches,
    combine_bid_result_summaries,
    claim_opening_enrichment,
    enqueue_opening_enrichment,
    extract_bid_award_operation,
    extract_opening_participants,
    finish_opening_enrichment,
    mark_opening_awards_checked,
    normalize_bid_results,
    replace_opening_participants,
    select_competitive_opening_participants,
    upsert_bid_results,
)
from teoria_pipelines.tasks.pps_contracts import (
    determine_backfill_windows,
    determine_incremental_window,
)


OPERATION_TASK_NAMES = {
    "list_goods_bid_awards": "물품 최종낙찰 목록 수집",
    "list_construction_bid_awards": "공사 최종낙찰 목록 수집",
    "list_service_bid_awards": "용역 최종낙찰 목록 수집",
    "list_foreign_bid_awards": "외자 최종낙찰 목록 수집",
}


@flow(name="나라장터 낙찰정보 일별 수집")
async def sync_pps_bid_result_window(
    window: CollectionWindow,
    pipeline_root: str = "/app/pipelines",
    pipeline_id: str = PIPELINE_ID,
) -> LoadSummary:
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    started_execution_id = start_pipeline_run(execution_id, pipeline_id, window)
    try:
        award_batches = []
        previous_batch = None
        for operation_id in AWARD_OPERATIONS:
            operation_task = extract_bid_award_operation.with_options(
                name=OPERATION_TASK_NAMES[operation_id]
            )
            previous_batch = await operation_task(
                started_execution_id, window, operation_id, pipeline_root, previous_batch
            )
            award_batches.append(previous_batch)
        awards = combine_bid_result_batches(
            execution_id, window, award_batches, ExtractedBatch(execution_id, window)
        )
        # Successful bid-result payloads are normalized and then discarded.
        # Pipeline-run counts and provider hashes on normalized rows retain the
        # operational provenance without duplicating the wire payload.
        award_raw_count = 0
        normalized_awards = normalize_bid_results(awards, award_raw_count)
        award_loaded = upsert_bid_results(normalized_awards)

        queue_class = "incremental" if pipeline_id == INCREMENTAL_PIPELINE_ID else "backfill"
        enqueue_opening_enrichment(awards, queue_class)
        loaded = combine_bid_result_summaries(
            award_raw_count, award_loaded, [], [], []
        )
        checkpointed = update_checkpoint(
            execution_id, pipeline_id, window.end, loaded.raw_records, loaded
        )
        return complete_pipeline_run(execution_id, checkpointed)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise


@flow(name="나라장터 개찰 참여업체 보강")
async def enrich_pps_bid_opening_participants(
    pipeline_root: str = "/app/pipelines", batch_size: int = 20,
    lease_minutes: int = 15, queue_mode: str = "incremental",
) -> LoadSummary:
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    today = date.today()
    window = CollectionWindow(today, today)
    started_execution_id = start_pipeline_run(
        execution_id, f"pps_bid_opening_{queue_mode}_enrichment", window
    )
    try:
        awards = claim_opening_enrichment(
            started_execution_id, queue_mode, batch_size, lease_minutes
        )
        if not awards.records:
            summary = LoadSummary()
            return complete_pipeline_run(execution_id, summary)
        result = await extract_opening_participants(
            started_execution_id, window, awards, pipeline_root
        )
        competitive = select_competitive_opening_participants(
            result.successful_awards, result.openings
        )
        normalized = normalize_bid_results(competitive, 0)
        loaded = replace_opening_participants(result.successful_awards, normalized)
        mark_opening_awards_checked(result.successful_awards, result.openings, loaded)
        finish_opening_enrichment(result)
        return complete_pipeline_run(execution_id, loaded)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise


@flow(name="나라장터 낙찰정보 증분 수집")
async def sync_pps_bid_results_incremental(
    pipeline_root: str = "/app/pipelines",
    lookback_days: int = 3,
    pipeline_id: str = INCREMENTAL_PIPELINE_ID,
) -> list[LoadSummary]:
    collection_window = determine_incremental_window(lookback_days)
    return [
        await sync_pps_bid_result_window(window, pipeline_root, pipeline_id)
        for window in split_windows(collection_window, 1)
    ]


@flow(name="나라장터 낙찰정보 Backfill")
async def sync_pps_bid_results_backfill(
    checkpoint_id: str,
    start_date: date,
    end_date: date,
    pipeline_root: str = "/app/pipelines",
    batch_days: int = 30,
) -> list[LoadSummary]:
    windows = determine_backfill_windows(
        checkpoint_id, start_date, end_date, batch_days, reverse=True
    )
    return [
        await sync_pps_bid_result_window(window, pipeline_root, checkpoint_id)
        for window in windows
    ]
