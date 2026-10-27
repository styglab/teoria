from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from prefect.states import Scheduled, Failed, Completed
from teoria.integrations.prefect import child_deployment as module


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [Completed(), Failed(), Scheduled()])
async def test_child_success_failure_and_timeout_cleanup(monkeypatch, state):
    child = SimpleNamespace(id="child", state=state)
    client = SimpleNamespace(
        read_flow_run=AsyncMock(return_value=child), set_flow_run_state=AsyncMock()
    )

    @asynccontextmanager
    async def context():
        yield client

    monkeypatch.setattr(module, "get_client", context)
    monkeypatch.setattr(module, "arun_deployment", AsyncMock(return_value=child))
    if state.is_completed():
        assert (
            await module.run_child_deployment(
                "flow/deployment", {}, key="idempotent", timeout=0.01
            )
            is child
        )
    elif state.is_final():
        with pytest.raises(RuntimeError, match="failed"):
            await module.run_child_deployment(
                "flow/deployment", {}, key="idempotent", timeout=0.01
            )
    else:
        with pytest.raises(TimeoutError):
            await module.run_child_deployment(
                "flow/deployment", {}, key="idempotent", timeout=0.01
            )
        assert client.set_flow_run_state.await_args.args[1].is_cancelling()
    assert module.arun_deployment.await_args.kwargs["as_subflow"] is True
