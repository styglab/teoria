"""Await a remote deployment without leaving queued work after parent cancellation."""

import asyncio

from prefect.client.orchestration import get_client
from prefect.deployments import arun_deployment
from prefect.states import Cancelling


async def run_child_deployment(
    name: str, parameters: dict, *, key: str, timeout: float = 900
):
    child = await arun_deployment(
        name=name,
        parameters=parameters,
        idempotency_key=key,
        timeout=0,
        as_subflow=True,
    )
    async with get_client() as client:

        async def wait():
            while True:
                current = await client.read_flow_run(child.id)
                if current.state is not None and current.state.is_final():
                    if not current.state.is_completed():
                        raise RuntimeError(
                            f"child deployment failed: {child.id} ({current.state.name})"
                        )
                    return current
                await asyncio.sleep(3)

        try:
            return await asyncio.wait_for(wait(), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            current = await client.read_flow_run(child.id)
            if current.state is None or not current.state.is_final():
                await client.set_flow_run_state(
                    child.id,
                    Cancelling(message="Parent workflow cancelled or timed out"),
                    force=True,
                )
            raise
