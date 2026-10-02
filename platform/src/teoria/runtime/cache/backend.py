from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any

from redis.asyncio import Redis

from teoria.runtime.capability.runner import CapabilityResult


logger = logging.getLogger(__name__)


class RuntimeCache(ABC):
    def __init__(self, *, prefix: str = "teoria:runtime") -> None:
        self.prefix = prefix.rstrip(":")

    def key(self, registry_version: str, capability_id: str, inputs: dict[str, Any]) -> str:
        normalized = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        return f"{self.prefix}:{registry_version}:{capability_id}:{digest}"

    @abstractmethod
    async def get(self, key: str) -> CapabilityResult | None: ...

    @abstractmethod
    async def set(self, key: str, value: CapabilityResult, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None: ...

    @abstractmethod
    async def release_lock(self, key: str, token: str) -> None: ...


class NullRuntimeCache(RuntimeCache):
    async def get(self, key: str) -> CapabilityResult | None:
        return None

    async def set(self, key: str, value: CapabilityResult, ttl_seconds: int) -> None:
        return None

    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        return uuid.uuid4().hex

    async def release_lock(self, key: str, token: str) -> None:
        return None


class MemoryRuntimeCache(RuntimeCache):
    def __init__(self, *, prefix: str = "teoria:runtime", max_entries: int = 2048) -> None:
        super().__init__(prefix=prefix)
        self.max_entries = max_entries
        self.values: OrderedDict[str, tuple[float, CapabilityResult]] = OrderedDict()
        self.locks: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> CapabilityResult | None:
        cached = self.values.get(key)
        if cached is None:
            return None
        if time.monotonic() >= cached[0]:
            self.values.pop(key, None)
            return None
        self.values.move_to_end(key)
        return cached[1].model_copy(deep=True)

    async def set(self, key: str, value: CapabilityResult, ttl_seconds: int) -> None:
        self.values[key] = (time.monotonic() + ttl_seconds, value.model_copy(deep=True))
        self.values.move_to_end(key)
        while len(self.values) > self.max_entries:
            self.values.popitem(last=False)

    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        now = time.monotonic()
        current = self.locks.get(key)
        if current and current[1] > now:
            return None
        token = uuid.uuid4().hex
        self.locks[key] = (token, now + ttl_seconds)
        return token

    async def release_lock(self, key: str, token: str) -> None:
        if self.locks.get(key, (None,))[0] == token:
            self.locks.pop(key, None)


class RedisRuntimeCache(RuntimeCache):
    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, url: str, *, prefix: str = "teoria:runtime") -> None:
        super().__init__(prefix=prefix)
        self.client = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> CapabilityResult | None:
        try:
            payload = await self.client.get(key)
            return CapabilityResult.model_validate_json(payload) if payload else None
        except Exception as exc:
            logger.warning("runtime cache get failed key=%s error=%s", key, exc)
            return None

    async def set(self, key: str, value: CapabilityResult, ttl_seconds: int) -> None:
        try:
            await self.client.set(key, value.model_dump_json(), ex=ttl_seconds)
        except Exception as exc:
            logger.warning("runtime cache set failed key=%s error=%s", key, exc)

    async def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        token = uuid.uuid4().hex
        try:
            acquired = await self.client.set(f"{key}:lock", token, nx=True, ex=ttl_seconds)
            return token if acquired else None
        except Exception as exc:
            logger.warning("runtime cache lock failed key=%s error=%s", key, exc)
            return token

    async def release_lock(self, key: str, token: str) -> None:
        try:
            await self.client.eval(self._RELEASE_SCRIPT, 1, f"{key}:lock", token)
        except Exception as exc:
            logger.warning("runtime cache unlock failed key=%s error=%s", key, exc)


def create_runtime_cache(backend: str, *, url: str, prefix: str) -> RuntimeCache:
    if backend == "redis":
        return RedisRuntimeCache(url, prefix=prefix)
    if backend == "disabled":
        return NullRuntimeCache(prefix=prefix)
    return MemoryRuntimeCache(prefix=prefix)
