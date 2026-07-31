from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.checkpoints import split_windows
from teoria_pipelines.models import CollectionWindow, LoadSummary
from teoria_pipelines.tasks import (
    complete_pipeline_run,
    combine_extracted_batches,
    determine_collection_window,
    extract_contract_operation,
    fail_pipeline_run,
    normalize_contracts,
    save_raw_records,
    start_pipeline_run,
    update_checkpoint,
    upsert_contracts,
)
from teoria_pipelines.tasks.pps_contracts import OPERATIONS


OPERATION_TASK_NAMES = {
    "list_goods_contracts": "상품 계약 API 수집",
    "list_construction_contracts": "공사 계약 API 수집",
    "list_service_contracts": "용역 계약 API 수집",
    "list_foreign_procurement_contracts": "외자 계약 API 수집",
}


@flow(name="나라장터 계약정보 일별 수집")
async def sync_pps_contract_window(window: CollectionWindow,
                                   pipeline_root: str = "/app/pipelines",
                                   parent_window: CollectionWindow | None = None) -> LoadSummary:
    del parent_window  # keeps the parent task-to-subflow dependency visible
    # Use the Prefect child Flow Run ID as the DB audit identity when executed
    # by Prefect, while keeping static visualization callable without a backend.
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    started_execution_id = start_pipeline_run(execution_id, window)
    try:
        batches = []
        previous_batch = None
        for operation_id in OPERATIONS:
            operation_task = extract_contract_operation.with_options(
                name=OPERATION_TASK_NAMES[operation_id]
            )
            previous_batch = await operation_task(
                started_execution_id,
                window,
                operation_id,
                pipeline_root,
                previous_batch,
            )
            batches.append(previous_batch)
        extracted = combine_extracted_batches(execution_id, window, batches, previous_batch)
        raw_count = save_raw_records(extracted)
        normalized = normalize_contracts(extracted, raw_count)
        loaded = upsert_contracts(normalized)
        checkpointed = update_checkpoint(
            execution_id,
            window,
            raw_count,
            loaded,
        )
        return complete_pipeline_run(execution_id, checkpointed)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise


@flow(name="나라장터 계약정보 수집")
async def sync_pps_contracts(start_date: date | None = None,
                             end_date: date | None = None,
                             pipeline_root: str = "/app/pipelines",
                             window_days: int = 1,
                             overlap_days: int = 2) -> list[LoadSummary]:
    """Collect a requested range, or continue from the checkpoint with overlap."""

    collection_window = determine_collection_window(start_date, end_date, overlap_days)
    summaries: list[LoadSummary] = []
    for window in split_windows(collection_window, window_days):
        summaries.append(
            await sync_pps_contract_window(window, pipeline_root, collection_window)
        )
    return summaries
