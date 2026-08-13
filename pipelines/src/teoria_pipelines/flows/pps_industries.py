from datetime import date
from uuid import UUID, uuid4

from prefect import flow
from prefect.runtime import flow_run

from teoria_pipelines.models import CollectionWindow
from teoria_pipelines.tasks.pps_contracts import complete_pipeline_run, fail_pipeline_run, start_pipeline_run, update_checkpoint
from teoria_pipelines.tasks.pps_industries import (
    PIPELINE_ID, extract_industries, load_industry_dictionary,
    normalize_industry_dictionary, save_industry_raw,
)


@flow(name="나라장터 업종 사전 주간 동기화")
async def sync_pps_industries(pipeline_root: str = "/app/pipelines"):
    today = date.today()
    window = CollectionWindow(today, today)
    run_id = flow_run.get_id()
    execution_id = UUID(run_id) if run_id else uuid4()
    start_pipeline_run(execution_id, PIPELINE_ID, window)
    try:
        extracted = await extract_industries(execution_id, pipeline_root)
        raw_count = save_industry_raw(extracted)
        rows = normalize_industry_dictionary(extracted, raw_count)
        loaded = load_industry_dictionary(rows)
        checkpointed = update_checkpoint(execution_id, PIPELINE_ID, today, raw_count, loaded)
        return complete_pipeline_run(execution_id, checkpointed)
    except BaseException as exc:
        fail_pipeline_run(execution_id, type(exc).__name__)
        raise
