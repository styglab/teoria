from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityResult


async def _cached(
    cache: Any | None,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
) -> tuple[Any, CapabilityResult | None]:
    if cache is None:
        return None, None
    version = catalog.release.version if catalog.release else "unpublished"
    key = cache.key(version, capability_id, inputs)
    return key, await cache.get(key)


async def _store(
    cache: Any | None, key: Any, result: CapabilityResult, ttl: int = 60
) -> CapabilityResult:
    if cache is not None:
        await cache.set(key, result, ttl)
    return result
