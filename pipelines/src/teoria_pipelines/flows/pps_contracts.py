from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.checkpoints import split_windows
from teoria_pipelines.models import CollectionWindow, LoadSummary
from teoria_pipelines.tasks import (
    claim_backfill_gaps,
    complete_operation,
    complete_pipeline_run,
    determine_collection_window,
    enqueue_contract_event_ledger_refresh,
    extract_contract_operation,
    fail_pipeline_run,
    get_completed_operation,
    normalize_contracts,
    record_backfill_gap,
    refresh_contract_event_ledger,
    resolve_backfill_gap,
    save_raw_records,
    start_pipeline_run,
    update_checkpoint,
    upsert_contracts,
)
from teoria_pipelines.connectors.pps_contracts import ConnectorResponseError
from teoria_pipelines.tasks.pps_contracts import (
    BACKFILL_PIPELINE_ID,
    INCREMENTAL_PIPELINE_ID,
    OPERATIONS,
    PIPELINE_ID,
    determine_backfill_windows,
    determine_incremental_window,
)


OPERATION_TASK_NAMES = {
    "list_goods_contracts": "상품 계약 API 수집",
    "list_construction_contracts": "공사 계약 API 수집",
    "list_service_contracts": "용역 계약 API 수집",
    "list_foreign_procurement_contracts": "외자 계약 API 수집",
}


@flow(name="나라장터 계약정보 일별 수집")
async def sync_pps_contract_window(window: CollectionWindow,
                                   pipeline_root: str = "/app/pipelines",
                                   parent_window: CollectionWindow | None = None,
                                   pipeline_id: str = PIPELINE_ID,
                                   checkpoint_cursor: date | None = None,
                                   resume_completed_operations: bool = False,
                                   continue_on_operation_error: bool = False) -> LoadSummary:
    del parent_window  # keeps the parent task-to-subflow dependency visible
    # Use the Prefect child Flow Run ID as the DB audit identity when executed
    # by Prefect, while keeping static visualization callable without a backend.
    prefect_run_id = flow_run.get_id()
    execution_id = UUID(prefect_run_id) if prefect_run_id else uuid4()
    started_execution_id = start_pipeline_run(execution_id, pipeline_id, window)
    try:
        summaries: list[LoadSummary] = []
        previous_batch = None
        for operation_id in OPERATIONS:
            if resume_completed_operations:
                completed = get_completed_operation(pipeline_id, window, operation_id)
                if completed is not None:
                    summaries.append(completed)
                    continue
            operation_task = extract_contract_operation.with_options(
                name=OPERATION_TASK_NAMES[operation_id]
            )
            try:
                previous_batch = await operation_task(
                    started_execution_id,
                    window,
                    operation_id,
                    pipeline_root,
                    previous_batch,
                )
            except ConnectorResponseError as exc:
                if not continue_on_operation_error:
                    raise
                record_backfill_gap(
                    pipeline_id, window, operation_id,
                    f"{type(exc).__name__}: {exc}",
                )
                previous_batch = None
                continue
            raw_count = save_raw_records(previous_batch)
            normalized = normalize_contracts(previous_batch, raw_count)
            loaded = upsert_contracts(normalized)
            enqueue_contract_event_ledger_refresh(normalized, loaded)
            summaries.append(complete_operation(
                pipeline_id, window, operation_id, execution_id, raw_count, loaded
            ))
        loaded = _sum_summaries(summaries)
        checkpointed = update_checkpoint(
            execution_id,
            pipeline_id,
            checkpoint_cursor or window.end,
            loaded.raw_records,
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


@flow(name="나라장터 계약정보 증분 수집")
async def sync_pps_contract_incremental(
    pipeline_root: str = "/app/pipelines",
    lookback_days: int = 3,
    pipeline_id: str = INCREMENTAL_PIPELINE_ID,
) -> list[LoadSummary]:
    """Refresh recent contracts independently of historical backfill progress."""

    collection_window = determine_incremental_window(lookback_days)
    summaries: list[LoadSummary] = []
    for window in split_windows(collection_window, 1):
        summaries.append(
            await sync_pps_contract_window(
                window,
                pipeline_root,
                collection_window,
                pipeline_id,
                window.end,
            )
        )
    return summaries


@flow(name="나라장터 계약정보 Backfill")
async def sync_pps_contract_backfill(
    checkpoint_id: str,
    start_date: date,
    end_date: date,
    pipeline_root: str = "/app/pipelines",
    batch_days: int = 1,
) -> list[LoadSummary]:
    """Move from the latest date backward through an independent historical range."""

    windows = determine_backfill_windows(
        checkpoint_id, start_date, end_date, batch_days, reverse=True
    )
    summaries: list[LoadSummary] = []
    for window in windows:
        summaries.append(
            await sync_pps_contract_window(
                window,
                pipeline_root,
                None,
                checkpoint_id,
                window.end,
                True,
                True,
            )
        )
    return summaries


@flow(name="나라장터 계약정보 Backfill 결손 재처리")
async def retry_pps_contract_backfill_gaps(
    pipeline_root: str = "/app/pipelines",
    source_pipeline_id: str = BACKFILL_PIPELINE_ID,
    batch_size: int = 1,
    retry_days: int = 1,
) -> list[LoadSummary]:
    gaps = claim_backfill_gaps(source_pipeline_id, batch_size, retry_days)
    summaries: list[LoadSummary] = []
    for gap in gaps:
        start = gap["window_start"]
        end = gap["window_end"]
        window = CollectionWindow(
            date.fromisoformat(start) if isinstance(start, str) else start,
            date.fromisoformat(end) if isinstance(end, str) else end,
        )
        operation_id = gap["operation_id"]
        execution_id = uuid4()
        started_execution_id = start_pipeline_run(
            execution_id, f"{source_pipeline_id}_gap_retry", window
        )
        try:
            batch = await extract_contract_operation.with_options(
                name=f"계약 Backfill 결손 재시도: {operation_id}"
            )(
                started_execution_id, window, operation_id, pipeline_root, None,
                (20, 10, 1), 1,
            )
            raw_count = save_raw_records(batch)
            normalized = normalize_contracts(batch, raw_count)
            loaded = upsert_contracts(normalized)
            enqueue_contract_event_ledger_refresh(normalized, loaded)
            summary = complete_operation(
                source_pipeline_id, window, operation_id, execution_id,
                raw_count, loaded,
            )
            resolve_backfill_gap(source_pipeline_id, window, operation_id)
            summaries.append(complete_pipeline_run(execution_id, summary))
        except BaseException as exc:
            fail_pipeline_run(execution_id, type(exc).__name__)
            raise
    return summaries


def _sum_summaries(summaries: list[LoadSummary]) -> LoadSummary:
    return LoadSummary(
        raw_records=sum(item.raw_records for item in summaries),
        contracts=sum(item.contracts for item in summaries),
        suppliers=sum(item.suppliers for item in summaries),
        organizations=sum(item.organizations for item in summaries),
        demand_organizations=sum(item.demand_organizations for item in summaries),
    )


@flow(name="계약 사건 사전집계 갱신")
def refresh_pps_contract_event_ledger(batch_size: int = 5) -> int:
    return refresh_contract_event_ledger(batch_size)
