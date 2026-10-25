from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from prefect.client.schemas.objects import StateType
from teoria.integrations.data_operations.persistence import PostgresStore
from teoria.integrations.data_operations.recovery import reconcile_finished_pipeline_runs


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *_args):
        return None


@pytest.mark.parametrize(
    "state", [StateType.RUNNING, StateType.PENDING, StateType.SCHEDULED]
)
@pytest.mark.asyncio
async def test_worker_restart_preserves_active_runs_and_parents(state):
    store = MagicMock(spec=PostgresStore)
    store.list_running_runs.return_value = [{"execution_id": uuid4()}]
    client = SimpleNamespace(
        read_flow_run=AsyncMock(return_value=SimpleNamespace(state_type=state)),
        set_flow_run_state=AsyncMock(),
    )
    result = await reconcile_finished_pipeline_runs(
        store, client_factory=lambda: _ClientContext(client)
    )
    assert result == []
    store.fail_run_if_running.assert_not_called()
    client.set_flow_run_state.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [StateType.FAILED, StateType.CANCELLED, StateType.CRASHED, StateType.COMPLETED],
)
@pytest.mark.asyncio
async def test_reconciliation_fails_only_confirmed_finished_rows(state):
    execution_id = uuid4()
    store = MagicMock(spec=PostgresStore)
    store.list_running_runs.return_value = [{"execution_id": execution_id}]
    client = SimpleNamespace(
        read_flow_run=AsyncMock(return_value=SimpleNamespace(state_type=state))
    )
    assert await reconcile_finished_pipeline_runs(
        store, client_factory=lambda: _ClientContext(client)
    ) == [execution_id]
    store.fail_run_if_running.assert_called_once_with(
        execution_id, f"IncompleteRunAfter{state.value.title()}"
    )


@pytest.mark.asyncio
async def test_unlinked_execution_id_is_not_assumed_orphaned():
    from prefect.exceptions import ObjectNotFound

    store = MagicMock(spec=PostgresStore)
    store.list_running_runs.return_value = [{"execution_id": uuid4()}]
    client = SimpleNamespace(
        read_flow_run=AsyncMock(side_effect=ObjectNotFound(http_exc=None))
    )
    assert (
        await reconcile_finished_pipeline_runs(
            store, client_factory=lambda: _ClientContext(client)
        )
        == []
    )
    store.fail_run_if_running.assert_not_called()


async def test_list_running_runs_only_queries_active_rows() -> None:
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    execution_id = uuid4()
    connection.execute.return_value.fetchall.return_value = [
        (execution_id, "pipeline", "start", "end", "started")
    ]

    with patch(
        "teoria.integrations.data_operations.persistence.connection.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        rows = await PostgresStore("postgresql://unused").list_running_runs()

    assert rows == [
        {
            "execution_id": execution_id,
            "pipeline_id": "pipeline",
            "window_start": "start",
            "window_end": "end",
            "started_at": "started",
        }
    ]
    assert "WHERE status='running'" in connection.execute.call_args.args[0]


@pytest.mark.asyncio
async def test_reconciliation_does_not_overwrite_a_concurrently_completed_row():
    store = MagicMock(spec=PostgresStore)
    store.list_running_runs.return_value = [{"execution_id": uuid4()}]
    store.fail_run_if_running.return_value = False
    client = SimpleNamespace(
        read_flow_run=AsyncMock(
            return_value=SimpleNamespace(state_type=StateType.COMPLETED)
        )
    )
    assert (
        await reconcile_finished_pipeline_runs(
            store, client_factory=lambda: _ClientContext(client)
        )
        == []
    )
