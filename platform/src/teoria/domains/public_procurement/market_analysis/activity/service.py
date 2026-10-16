from __future__ import annotations

import time
from typing import Any

import psycopg

from teoria.domains.public_procurement.market_analysis.activity.reader import (
    ProcurementActivityReader,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)

from .aggregation import build_activity_events
from .filters import filter_activity_records
from .lifecycle import expand_activity_records, resolve_activity_stages
from .presentation import build_activity_result
from .query import ActivityQuery
from .result_selection import select_activity_page


async def execute_procurement_activity_search(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementActivityReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    request = ActivityQuery.from_inputs(inputs, capability_id)
    try:
        notices, awards, contracts, participated_notice_ids = await (
            reader or ProcurementActivityReader()
        ).find(
            catalog,
            organization_code=request.organization_code,
            period_from=request.period_from,
            period_to=request.period_to,
            company_number=request.company_number,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    events = build_activity_events(
        notices,
        awards,
        contracts,
        participated_notice_ids,
        organization_code=request.organization_code,
        period_from=request.period_from,
        period_to=request.period_to,
    )
    staged = resolve_activity_stages(events.activities, request.stage_as_of)
    expanded = expand_activity_records(staged, events.contract_classifications)
    filtered = filter_activity_records(expanded, request, events)
    page = select_activity_page(filtered, request)
    return build_activity_result(
        catalog, capability_id, request, events.organization_name, page, started
    )
