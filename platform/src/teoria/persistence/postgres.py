"""Native asynchronous PostgreSQL connections with bounded in-flight work."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakKeyDictionary, WeakValueDictionary

import psycopg

# Prefect and CLI commands may create successive event loops in one process.
# A semaphore belongs to one loop; weak references also release idle DSN keys.
_limits: WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    WeakValueDictionary[tuple[str, int], asyncio.Semaphore],
] = WeakKeyDictionary()


@asynccontextmanager
async def connect(
    database_url: str, **options: Any
) -> AsyncIterator[psycopg.AsyncConnection]:
    """Limit active connections and close/commit/rollback on context exit."""
    limit = int(os.environ.get("TEORIA_DATABASE_CONCURRENCY_LIMIT", "10"))
    if limit < 1:
        raise ValueError("TEORIA_DATABASE_CONCURRENCY_LIMIT must be positive")
    loop = asyncio.get_running_loop()
    limits = _limits.setdefault(loop, WeakValueDictionary())
    key = (database_url, limit)
    semaphore = limits.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        limits[key] = semaphore
    async with semaphore:
        async with await psycopg.AsyncConnection.connect(
            database_url, **options
        ) as connection:
            yield connection
