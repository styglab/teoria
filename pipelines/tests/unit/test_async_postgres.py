import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from teoria_pipelines.persistence.connection import connect


async def test_connection_limit_and_cancelled_waiter_release_slots(monkeypatch):
    monkeypatch.setenv("TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT", "1")
    entered, release = asyncio.Event(), asyncio.Event()
    active = maximum = closed = 0

    @asynccontextmanager
    async def connection():
        nonlocal active, maximum, closed
        active += 1
        maximum = max(maximum, active)
        try:
            yield object()
        finally:
            active -= 1
            closed += 1

    driver = AsyncMock(side_effect=lambda *args, **kwargs: connection())
    monkeypatch.setattr(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        driver,
    )

    async def hold():
        async with connect("postgresql://synthetic"):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(hold())
    await asyncio.wait_for(entered.wait(), 1)
    waiter = asyncio.create_task(hold())
    await asyncio.sleep(0)
    assert driver.await_count == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    release.set()
    await asyncio.wait_for(hold(), 1)
    assert maximum == 1 and active == 0 and closed == 2


async def test_failed_connection_does_not_leak_capacity(monkeypatch):
    monkeypatch.setenv("TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT", "1")

    @asynccontextmanager
    async def connection():
        yield object()

    driver = AsyncMock(side_effect=[OSError("synthetic failure"), connection()])
    monkeypatch.setattr(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        driver,
    )
    with pytest.raises(OSError, match="synthetic failure"):
        async with connect("postgresql://synthetic"):
            pytest.fail("Failed connection must not yield")

    async def reconnect():
        async with connect("postgresql://synthetic"):
            pass

    await asyncio.wait_for(reconnect(), 1)
    assert driver.await_count == 2


@pytest.mark.parametrize("limit", ["0", "-1", "invalid"])
async def test_invalid_limit_fails_before_connecting(monkeypatch, limit):
    monkeypatch.setenv("TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT", limit)
    driver = AsyncMock()
    monkeypatch.setattr(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        driver,
    )
    with pytest.raises(ValueError):
        async with connect("postgresql://synthetic"):
            pass
    driver.assert_not_awaited()
