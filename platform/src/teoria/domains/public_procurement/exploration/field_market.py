from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)

from .cache import _cached, _store
from .filters import (
    _with_period,
    _with_region_filter,
)
from .presentation import _number, _object
from .reader import ProcurementExplorationReader


async def execute_procurement_field_market(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementExplorationReader | None = None,
    cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    inputs = _with_region_filter(_with_period(inputs, capability_id), capability_id)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, updated_at = await resolved.field_market(catalog, inputs=inputs)
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    yearly = [
        {
            key: (_number(value) if isinstance(value, Decimal) else value)
            for key, value in row.items()
            if key != "updated_at"
        }
        for row in rows
    ]
    summary = {
        "contract_count": sum(int(row["contract_count"]) for row in rows),
        "total_attributed_contract_amount": _number(
            sum(
                (
                    row["total_attributed_contract_amount"] or Decimal("0")
                    for row in rows
                ),
                Decimal("0"),
            )
        )
        if rows
        else None,
        "missing_attributed_amount_count": sum(
            int(row["missing_attributed_amount_count"]) for row in rows
        ),
        "organization_count": None,
        "company_count": None,
    }
    properties = {
        "procurement_field_market_id": f"{inputs['field_code']}:{inputs['period_from_year']}:{inputs['period_to_year']}",
        "contract_count": summary["contract_count"],
    }
    return await _store(
        cache,
        cache_key,
        CapabilityResult(
            capability_id=capability_id,
            objects=[
                _object(
                    "procurement_field_market",
                    properties["procurement_field_market_id"],
                    properties,
                    capability_id,
                )
            ],
            outcome={
                "field_code": inputs["field_code"],
                "summary": summary,
                "yearly": yearly,
                "updated_at": updated_at,
                "analysis_basis": {
                    "scope": "runtime_collected_contract_ledger",
                    "contract_date": "first_contract_date",
                    "amount": "attributed_latest_contract_amount",
                    "period_from_year": inputs["period_from_year"],
                    "period_to_year": inputs["period_to_year"],
                    "work_type": inputs.get("work_type"),
                    "region_basis": inputs.get("region_basis"),
                    "region_code": inputs.get("region_code"),
                    "region_codes": inputs.get("region_codes"),
                },
                "coverage": {
                    "is_full_market": False,
                    "sample": True,
                    "missing_amount_count": summary["missing_attributed_amount_count"],
                    "region_filter": (
                        "linked_structured_bid_notice_restriction"
                        if inputs.get("region_basis")
                        else "not_requested"
                    ),
                },
            },
        ),
        60,
    )
