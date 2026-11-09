from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from teoria.platform.access_control.policy import PolicyDecision, PolicyPrincipal


class ContextQueryHandler(Protocol):
    def describe(self, question: str) -> dict[str, Any]: ...

    async def plan(
        self, question: str, *, as_of: date, principal: PolicyPrincipal,
    ) -> dict[str, Any]: ...

    async def execute(
        self, plan: dict[str, Any], principal: PolicyPrincipal, decision: PolicyDecision,
    ) -> dict[str, Any]: ...


class UnconfiguredQueries:
    def describe(self, question: str) -> dict[str, Any]:
        raise ValueError("No active domain query handler is configured")

    async def plan(
        self, question: str, *, as_of: date, principal: PolicyPrincipal,
    ) -> dict[str, Any]:
        raise ValueError("No active domain query handler is configured")

    async def execute(
        self, plan: dict[str, Any], principal: PolicyPrincipal, decision: PolicyDecision,
    ) -> dict[str, Any]:
        raise ValueError("No active domain query handler is configured")
