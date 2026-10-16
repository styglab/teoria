"""Reconcile durable ingestion rows only when Prefect confirms termination."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from teoria_pipelines.persistence import PostgresStore


async def reconcile_finished_pipeline_runs(
    store: PostgresStore,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> list[UUID]:
    from prefect.client.schemas.objects import StateType
    from prefect.exceptions import ObjectNotFound

    if client_factory is None:
        from prefect.client.orchestration import get_client

        client_factory = get_client

    # A worker restart says nothing about independent Jobs or other workers.
    # Missing Prefect IDs can also belong to domain-generated execution IDs.
    terminal = {
        StateType.FAILED,
        StateType.CANCELLED,
        StateType.CRASHED,
        StateType.COMPLETED,
    }
    reconciled: list[UUID] = []
    async with client_factory() as client:
        for run in await store.list_running_runs():
            execution_id = run["execution_id"]
            try:
                flow_run = await client.read_flow_run(execution_id)
            except ObjectNotFound:
                continue
            if flow_run.state_type not in terminal:
                continue
            # A completed Flow cannot prove a missing durable load completed.
            # Do not advance checkpoints or manufacture successful ingestion.
            changed = await store.fail_run_if_running(
                execution_id, f"IncompleteRunAfter{flow_run.state_type.value.title()}"
            )
            if changed:
                reconciled.append(execution_id)
    return reconciled
