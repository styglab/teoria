from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from teoria.features.access_control.policy import PolicyDecision, PolicyPrincipal


class ContextResolver(Protocol):
    async def __call__(self, term: str, *, purpose: str | None = None) -> dict[str, Any] | None: ...


class ContextQueryHandler(Protocol):
    def describe(self, question: str) -> dict[str, Any]: ...

    async def plan(
        self, question: str, *, as_of: date, principal: PolicyPrincipal,
    ) -> dict[str, Any]: ...

    async def execute(
        self, plan: dict[str, Any], principal: PolicyPrincipal, decision: PolicyDecision,
    ) -> dict[str, Any]: ...
