from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prefect.client.schemas.objects import StateType

from teoria_pipelines.persistence import PostgresStore
from teoria_pipelines.recovery import recover_orphaned_pipeline_runs


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
async def test_recovery_cancels_orphan_and_parent_before_failing_durable_run() -> None:
    execution_id = uuid4()
    parent_task_id = uuid4()
    parent_flow_id = uuid4()
    store = MagicMock()
    store.list_running_runs.return_value = [{"execution_id": execution_id}]
    client = SimpleNamespace(
        read_flow_run=AsyncMock(side_effect=[
            SimpleNamespace(
                parent_task_run_id=parent_task_id,
                state_type=StateType.RUNNING,
            ),
            SimpleNamespace(parent_task_run_id=None, state_type=StateType.RUNNING),
        ]),
        read_task_run=AsyncMock(
            return_value=SimpleNamespace(flow_run_id=parent_flow_id)
        ),
        set_flow_run_state=AsyncMock(),
    )

    recovered = await recover_orphaned_pipeline_runs(
        store, client_factory=lambda: _ClientContext(client)
    )

    assert recovered == [execution_id]
    assert [call.args[0] for call in client.set_flow_run_state.await_args_list] == [
        execution_id, parent_flow_id,
    ]
    store.fail_run.assert_called_once_with(execution_id, "WorkerRestart")


def test_list_running_runs_only_queries_active_rows() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    execution_id = uuid4()
    connection.execute.return_value.fetchall.return_value = [
        (execution_id, "pipeline", "start", "end", "started")
    ]

    with patch(
        "teoria_pipelines.persistence.postgres_store.base.psycopg.connect",
        return_value=connection,
    ):
        rows = PostgresStore("postgresql://unused").list_running_runs()

    assert rows == [{
        "execution_id": execution_id,
        "pipeline_id": "pipeline",
        "window_start": "start",
        "window_end": "end",
        "started_at": "started",
    }]
    assert "WHERE status='running'" in connection.execute.call_args.args[0]
