"""Exercise queue admission against a real, isolated Prefect API server."""

from uuid import uuid4

import pytest
from prefect import flow
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import WorkPoolUpdate
from prefect.states import Completed, Pending
from prefect.testing.utilities import prefect_test_harness
from teoria.integrations.prefect.deployment import configure_pool


@pytest.fixture(scope="module")
def prefect_server():
    with prefect_test_harness():
        yield


@pytest.mark.parametrize("backend", ["process", "kubernetes"])
@pytest.mark.asyncio
async def test_queue_priority_concurrency_and_slot_release(
    prefect_server, monkeypatch, backend
):
    if backend == "kubernetes":
        pytest.importorskip("prefect_kubernetes")
    monkeypatch.setenv("TEORIA_PIPELINE_JOB_IMAGE", "ghcr.io/example/pipelines:test")
    monkeypatch.setenv("TEORIA_PIPELINE_CONCURRENCY", "2")

    @flow(name=f"queue-check-{uuid4().hex}")
    def sample():
        return 1

    async with get_client() as client:
        metadata_pool = await configure_pool(client, backend=backend, kind="metadata")
        metadata = await client.read_work_pool(metadata_pool)
        assert metadata.type == "process" and metadata.concurrency_limit == 1
        pool = await configure_pool(client, backend=backend, kind="ingestion")
        await client.update_work_pool(pool, WorkPoolUpdate(is_paused=True))
        await configure_pool(client, backend=backend, kind="ingestion")
        actual = await client.read_work_pool(pool)
        assert actual.type == backend and actual.concurrency_limit == 2
        assert actual.is_paused is True
        await client.update_work_pool(pool, WorkPoolUpdate(is_paused=False))
        queue = await client.read_work_queue_by_name("documents", work_pool_name=pool)
        assert queue.concurrency_limit == 2
        flow_id = await client.create_flow(sample)
        deployment_id = await client.create_deployment(
            flow_id=flow_id, name="documents", work_pool_name=pool,
            work_queue_name="documents",
        )
        runs = [await client.create_flow_run_from_deployment(deployment_id) for _ in range(3)]
        offered = await client.get_scheduled_flow_runs_for_work_pool(pool)
        assert len(offered) == 2
        assert all(item.work_queue_id == queue.id for item in offered)
        await client.set_flow_run_state(runs[0].id, Pending(), force=True)
        await client.set_flow_run_state(runs[1].id, Pending(), force=True)
        assert await client.get_scheduled_flow_runs_for_work_pool(pool) == []
        await client.set_flow_run_state(runs[0].id, Completed(), force=True)
        offered = await client.get_scheduled_flow_runs_for_work_pool(pool)
        assert [item.flow_run.id for item in offered] == [runs[2].id]
        await client.delete_work_pool(pool)
        await client.delete_work_pool(metadata_pool)


@pytest.mark.asyncio
async def test_process_worker_executes_flow_and_retries_before_checkpoint(
    prefect_server, tmp_path
):
    import asyncio

    from prefect.workers.process import ProcessWorker

    source = tmp_path / "retry_flow.py"
    source.write_text("""from pathlib import Path
from prefect import flow

@flow(name="execution-retry-check", retries=1, retry_delay_seconds=0)
def execute(directory: str):
    root = Path(directory)
    attempt = root / "attempt"
    if not attempt.exists():
        attempt.write_text("first")
        raise RuntimeError("synthetic failure before durable completion")
    (root / "checkpoint").write_text("completed")
""")
    from prefect.flows import load_flow_from_entrypoint

    sample = load_flow_from_entrypoint(f"{source}:execute")
    async with get_client() as client:
        pool = await configure_pool(client, backend="process", kind="ingestion")
        flow_id = await client.create_flow(sample)
        deployment_id = await client.create_deployment(
            flow_id=flow_id,
            name="retry-check",
            work_pool_name=pool,
            work_queue_name="documents",
            entrypoint=f"{source}:execute",
            path=str(tmp_path),
            pull_steps=[],
            parameters={"directory": str(tmp_path)},
        )
        run = await client.create_flow_run_from_deployment(deployment_id)
        worker = ProcessWorker(work_pool_name=pool, limit=2)
        await asyncio.wait_for(worker.start(run_once=True), timeout=90)
        result = await client.read_flow_run(run.id)
        assert result.state.is_completed()
        assert result.run_count == 2
        assert (tmp_path / "checkpoint").read_text() == "completed"
        await client.delete_work_pool(pool)
