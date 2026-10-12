from __future__ import annotations

from typing import TYPE_CHECKING

from teoria.context.query import ContextQueryHandler, ContextResolver
from teoria.context.runtime_client import ContextRuntimeClient
from teoria.domains.public_procurement.context import PublicProcurementQueries

if TYPE_CHECKING:
    from teoria.context.service import ContextExecutionPolicy


def create_query_handler(
    resolve: ContextResolver,
    runtime_client: ContextRuntimeClient | None,
    policy: ContextExecutionPolicy,
) -> ContextQueryHandler:
    return PublicProcurementQueries(resolve, runtime_client, policy)
