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
    save_raw_records,
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
    extract_bid_award_operation,
    extract_opening_participants,
    mark_opening_awards_checked,
    normalize_bid_results,
    replace_opening_participants,
    select_pending_opening_awards,
    split_opening_award_chunks,
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
    opening_chunk_size: int = 100,
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
        award_raw_count = save_raw_records(awards)
        normalized_awards = normalize_bid_results(awards, award_raw_count)
        award_loaded = upsert_bid_results(normalized_awards)

        pending_awards = select_pending_opening_awards(awards)
        opening_chunks = split_opening_award_chunks(pending_awards, opening_chunk_size)
        opening_raw_counts = []
        opening_loaded = []
        checked_counts = []
        for index, award_chunk in enumerate(opening_chunks, start=1):
            suffix = f"{index}/{len(opening_chunks)}"
            openings = await extract_opening_participants.with_options(
                name=f"공고별 개찰 참여업체 수집 {suffix}"
            )(started_execution_id, window, award_chunk, pipeline_root)
            opening_raw_count = save_raw_records.with_options(
                name=f"개찰 Raw 응답 저장 {suffix}"
            )(openings)
            normalized_openings = normalize_bid_results.with_options(
                name=f"개찰정보 정규화 {suffix}"
            )(openings, opening_raw_count)
            chunk_loaded = replace_opening_participants.with_options(
                name=f"개찰 참여업체 교체 저장 {suffix}"
            )(award_chunk, normalized_openings)
            checked_count = mark_opening_awards_checked.with_options(
                name=f"개찰 수집 완료상태 저장 {suffix}"
            )(award_chunk, openings, chunk_loaded)
            opening_raw_counts.append(opening_raw_count)
            opening_loaded.append(chunk_loaded)
            checked_counts.append(checked_count)
        loaded = combine_bid_result_summaries(
            award_raw_count, award_loaded, opening_raw_counts, opening_loaded, checked_counts
        )
        checkpointed = update_checkpoint(
            execution_id, pipeline_id, window.end, loaded.raw_records, loaded
        )
        return complete_pipeline_run(execution_id, checkpointed)
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
