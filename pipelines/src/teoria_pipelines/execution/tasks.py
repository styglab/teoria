from __future__ import annotations

from datetime import date
from uuid import UUID

from prefect import task

from teoria_pipelines.checkpoints import resolve_backfill_windows, resolve_incremental_window
from teoria_pipelines.execution.resources import _store
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, LoadSummary

VIZ_EXECUTION_ID = UUID(int=0)

VIZ_WINDOW = CollectionWindow(date(2026, 1, 1), date(2026, 1, 1))

VIZ_EXTRACTED = ExtractedBatch(execution_id=VIZ_EXECUTION_ID, window=VIZ_WINDOW)

VIZ_SUMMARY = LoadSummary()


@task(name="증분 수집 구간 결정", viz_return_value=VIZ_WINDOW)
def determine_incremental_window(lookback_days: int = 3) -> CollectionWindow:
    return resolve_incremental_window(lookback_days=lookback_days)


@task(name="Backfill 구간 결정", viz_return_value=[VIZ_WINDOW])
def determine_backfill_windows(checkpoint_id: str, start_date: date,
                               end_date: date,
                               batch_days: int = 30,
                               reverse: bool = False) -> list[CollectionWindow]:
    checkpoint = _store().get_checkpoint(checkpoint_id)
    return resolve_backfill_windows(
        start_date=start_date,
        end_date=end_date,
        checkpoint=checkpoint,
        batch_days=batch_days,
        reverse=reverse,
    )


@task(name="수집 실행 시작", viz_return_value=VIZ_EXECUTION_ID)
def start_pipeline_run(execution_id: UUID, pipeline_id: str,
                       window: CollectionWindow) -> UUID:
    _store().start_run(execution_id, pipeline_id, window)
    return execution_id


@task(name="Operation 응답 결합", viz_return_value=VIZ_EXTRACTED)
def combine_extracted_batches(execution_id: UUID, window: CollectionWindow,
                              batches: list[ExtractedBatch],
                              last_operation: ExtractedBatch) -> ExtractedBatch:
    del last_operation  # preserves the final Operation-to-merge edge in visualization
    return ExtractedBatch(
        execution_id=execution_id,
        window=window,
        records=[record for batch in batches for record in batch.records],
        pages=sum(batch.pages for batch in batches),
    )


@task(name="Raw 응답 저장", retries=2, retry_delay_seconds=5, viz_return_value=0)
def save_raw_records(batch: ExtractedBatch) -> int:
    return _store().save_raw_records(batch.records)


@task(name="Checkpoint 갱신", viz_return_value=VIZ_SUMMARY)
def update_checkpoint(execution_id: UUID, pipeline_id: str, cursor_date: date,
                      raw_record_count: int, load_summary: LoadSummary) -> LoadSummary:
    _store().update_checkpoint(pipeline_id, cursor_date, execution_id)
    return LoadSummary(
        raw_records=raw_record_count,
        contracts=load_summary.contracts,
        suppliers=load_summary.suppliers,
        organizations=load_summary.organizations,
        demand_organizations=load_summary.demand_organizations,
        notices=load_summary.notices,
        license_restrictions=load_summary.license_restrictions,
        participation_regions=load_summary.participation_regions,
        documents=load_summary.documents,
        industries=load_summary.industries,
        awards=load_summary.awards,
        opening_participants=load_summary.opening_participants,
    )


@task(name="수집 실행 완료", viz_return_value=VIZ_SUMMARY)
def complete_pipeline_run(execution_id: UUID, summary: LoadSummary) -> LoadSummary:
    _store().complete_run(execution_id, summary)
    return summary


@task(name="수집 실행 실패 기록")
def fail_pipeline_run(execution_id: UUID, error_code: str) -> None:
    _store().fail_run(execution_id, error_code)
