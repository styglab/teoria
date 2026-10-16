"""Native database I/O must yield and cancellation must roll back writes."""

import asyncio
import os
from uuid import uuid4

import pytest
from psycopg import sql

from teoria.persistence.postgres import connect

DATABASE_URL = os.environ.get("TEORIA_TEST_APP_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="TEORIA_TEST_APP_DATABASE_URL is not set"
)


async def test_query_yields_and_cancellation_rolls_back_transaction():
    table = sql.Identifier("async_io_probe_" + uuid4().hex)
    async with connect(DATABASE_URL) as connection:
        await connection.execute(sql.SQL("CREATE TABLE {} (id integer)").format(table))

    entered = asyncio.Event()
    active_connection = None

    async def write_and_wait():
        nonlocal active_connection
        async with connect(DATABASE_URL) as connection:
            active_connection = connection
            await connection.execute(sql.SQL("INSERT INTO {} VALUES (1)").format(table))
            entered.set()
            await connection.execute("SELECT pg_sleep(1)")

    task = asyncio.create_task(write_and_wait())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.sleep(0.02)
        assert not task.done(), "A database query must let the event loop keep running"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert active_connection.closed
        async with connect(DATABASE_URL) as connection:
            row = await (
                await connection.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(table)
                )
            ).fetchone()
        assert row == (0,)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        async with connect(DATABASE_URL) as connection:
            await connection.execute(sql.SQL("DROP TABLE {}").format(table))
