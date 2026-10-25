"""Default query behavior until a governed goods query handler is registered."""

from datetime import date
from typing import TYPE_CHECKING, Any

from teoria.policy import PolicyDecision, PolicyPrincipal
from teoria.context.query import ContextQueryHandler, ContextResolver
from teoria.context.runtime_client import ContextRuntimeClient


if TYPE_CHECKING:
    from teoria.context.service import ContextExecutionPolicy


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


def create_query_handler(
    resolve: ContextResolver,
    runtime_client: ContextRuntimeClient | None,
    policy: "ContextExecutionPolicy",
) -> ContextQueryHandler:
    return UnconfiguredQueries()
