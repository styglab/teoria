from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityResult

if TYPE_CHECKING:
    from teoria.runtime.capability.runner import CapabilityRunner


Processor = Callable[["CapabilityRunner", RegistryCatalog, str, dict[str, Any]], Awaitable[CapabilityResult]]
QueryHook = Callable[["CapabilityRunner", RegistryCatalog, CapabilityResult, datetime], Awaitable[CapabilityResult]]


class CapabilityHandlers:
    """Explicit executable handlers; Registry IDs are not Python import paths."""

    def __init__(self) -> None:
        self._processors: dict[str, Processor] = {}
        self._query_hooks: dict[str, QueryHook] = {}

    def register_processor(self, processor_id: str, handler: Processor) -> None:
        if processor_id in self._processors:
            raise ValueError(f"duplicate capability processor: {processor_id}")
        self._processors[processor_id] = handler

    def register_query_hook(self, capability_id: str, handler: QueryHook) -> None:
        if capability_id in self._query_hooks:
            raise ValueError(f"duplicate capability query hook: {capability_id}")
        self._query_hooks[capability_id] = handler

    def processor(self, processor_id: str | None) -> Processor | None:
        return self._processors.get(processor_id) if processor_id is not None else None

    def query_hook(self, capability_id: str) -> QueryHook | None:
        return self._query_hooks.get(capability_id)
