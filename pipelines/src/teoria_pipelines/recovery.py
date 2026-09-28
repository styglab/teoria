from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from teoria_pipelines.persistence import PostgresStore


async def recover_orphaned_pipeline_runs(
    store: PostgresStore,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> list[UUID]:
    """Cancel flow trees left behind when the sole ingestion worker restarts.

    This is intended to run before the compose-managed process worker starts.
    At that point no flow process from the previous worker container can still
    be alive, so every durable ``running`` row is an orphan.
    """
    if client_factory is None:
        from prefect.client.orchestration import get_client

        client_factory = get_client

    recovered: list[UUID] = []
    async with client_factory() as client:
        for run in store.list_running_runs():
            execution_id = run["execution_id"]
            await _cancel_flow_tree(client, execution_id)
            store.fail_run(execution_id, "WorkerRestart")
            recovered.append(execution_id)
    return recovered


async def _cancel_flow_tree(client: Any, flow_run_id: UUID) -> None:
    from prefect.client.schemas.objects import StateType
    from prefect.exceptions import ObjectNotFound
    from prefect.states import Cancelled

    try:
        flow_run = await client.read_flow_run(flow_run_id)
    except ObjectNotFound:
        return

    run_ids = [flow_run_id]
    if flow_run.parent_task_run_id:
        try:
            parent_task = await client.read_task_run(flow_run.parent_task_run_id)
        except ObjectNotFound:
            parent_task = None
        if parent_task is not None:
            run_ids.append(parent_task.flow_run_id)

    for run_id in run_ids:
        try:
            candidate = flow_run if run_id == flow_run_id else await client.read_flow_run(run_id)
            if candidate.state_type not in {
                StateType.COMPLETED, StateType.FAILED, StateType.CANCELLED, StateType.CRASHED,
            }:
                await client.set_flow_run_state(
                    run_id,
                    Cancelled(message="Ingestion worker restarted; orphaned run reconciled"),
                    force=True,
                )
        except ObjectNotFound:
            continue
