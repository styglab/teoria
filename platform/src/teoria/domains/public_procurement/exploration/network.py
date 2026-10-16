from __future__ import annotations

import hashlib
import json
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
    _digits,
    _with_period,
    _with_region_filter,
)
from .presentation import _edge, _number, _object
from .reader import ProcurementExplorationReader


async def execute_procurement_network(
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
    root_type = str(
        inputs.get("root_type") or ("field" if inputs.get("field_code") else "")
    )
    root_id = str(inputs.get("root_id") or inputs.get("field_code") or "").strip()
    if root_type not in {"organization", "company", "field"} or not root_id:
        raise CapabilityExecutionError(
            "invalid_root",
            "root_type/root_id or field_code is required",
            capability_id=capability_id,
        )
    if root_type == "field":
        inputs = {**inputs, "field_code": root_id}
    depth = int(inputs.get("depth", 1))
    first_limit = int(inputs.get("first_hop_limit", 20))
    second_limit = int(inputs.get("second_hop_limit", 50)) if depth == 2 else 0
    resolved = reader or ProcurementExplorationReader()
    try:
        first, second, snapshot = await resolved.network_edges(
            catalog,
            inputs=inputs,
            root_type=root_type,
            root_id=root_id,
            first_limit=first_limit,
            second_limit=second_limit,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    first_truncated = len(first) > first_limit
    second_truncated = len(second) > second_limit if second_limit else False
    edge_rows = [(row, 1) for row in first[:first_limit]] + [
        (row, 2) for row in second[:second_limit]
    ]
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    if root_type == "field":
        nodes[("field", root_id)] = {
            "type": "field",
            "id": root_id,
            "name": next(
                (row.get("field_name") for row in first if row.get("field_name")), None
            ),
            "is_root": True,
        }
    for row, _ in edge_rows:
        nodes[("organization", str(row["organization_code"]))] = {
            "type": "organization",
            "id": str(row["organization_code"]),
            "name": row.get("organization_name"),
            "is_root": root_type == "organization"
            and str(row["organization_code"]) == root_id,
        }
        nodes[("company", str(row["company_number"]))] = {
            "type": "company",
            "id": str(row["company_number"]),
            "name": row.get("company_name"),
            "is_root": root_type == "company" and str(row["company_number"]) == root_id,
        }
    edges = [_edge(row, hop=hop) for row, hop in edge_rows]
    total_contracts = sum(
        edge["relationships"]["contract"]["event_count"] for edge in edges
    )
    snapshot_id = snapshot.isoformat() if snapshot else None
    properties = {
        "procurement_network_id": hashlib.sha256(
            json.dumps([root_type, root_id, snapshot_id]).encode()
        ).hexdigest()[:24],
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
    return await _store(
        cache,
        cache_key,
        CapabilityResult(
            capability_id=capability_id,
            objects=[
                _object(
                    "procurement_network",
                    properties["procurement_network_id"],
                    properties,
                    capability_id,
                )
            ],
            outcome={
                "root": {"type": root_type, "id": root_id},
                "snapshot_id": snapshot_id,
                "nodes": list(nodes.values()),
                "edges": edges,
                "summary": {
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "contract_event_count": total_contracts,
                },
                "truncation": {
                    "truncated": first_truncated or second_truncated,
                    "first_hop_truncated": first_truncated,
                    "second_hop_truncated": second_truncated,
                    "omitted_node_count": None
                    if first_truncated or second_truncated
                    else 0,
                    "omitted_edge_count": None
                    if first_truncated or second_truncated
                    else 0,
                    "selection_basis": "contract_count_desc_attributed_amount_desc",
                },
                "coverage": {
                    "contract": "available",
                    "award": "not_in_read_model",
                    "observed_participation": "not_in_read_model",
                    "co_participation": "not_in_read_model",
                    "joint_contract": "not_in_read_model",
                    "region_filter": (
                        "linked_structured_bid_notice_restriction"
                        if inputs.get("region_basis")
                        else "not_requested"
                    ),
                },
                "analysis_basis": {
                    "contract_date": "first_contract_date",
                    "contract_amount": "latest_version_at_ledger_refresh",
                    "period_from_year": inputs["period_from_year"],
                    "period_to_year": inputs["period_to_year"],
                    "work_type": inputs.get("work_type"),
                    "field_code": inputs.get("field_code"),
                    "region_basis": inputs.get("region_basis"),
                    "region_code": inputs.get("region_code"),
                    "region_codes": inputs.get("region_codes"),
                },
                "updated_at": snapshot,
            },
        ),
        60,
    )


async def execute_network_organization_company_relationship(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementExplorationReader | None = None,
) -> CapabilityResult:
    inputs = _with_region_filter(_with_period(inputs, capability_id), capability_id)
    resolved = reader or ProcurementExplorationReader()
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    try:
        events, summary, snapshot = await resolved.relationship_events(
            catalog, inputs=inputs, offset=(page - 1) * page_size, limit=page_size
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    snapshot_id = snapshot.isoformat() if snapshot else None
    if inputs.get("snapshot_id") and str(inputs["snapshot_id"]) != snapshot_id:
        raise CapabilityExecutionError(
            "stale_snapshot",
            "requested network snapshot is no longer available",
            capability_id=capability_id,
        )
    total = int(summary.get("contract_count") or 0)
    properties = {
        "organization_company_relationship_id": f"{inputs['organization_code']}:{_digits(inputs['business_registration_number'])}",
        "organization_code": inputs["organization_code"],
        "company_number": _digits(inputs["business_registration_number"]),
        "award_event_count": 0,
        "unique_project_count": total,
        "contract_event_count": total,
        "contract_version_count": int(summary.get("contract_version_count") or 0),
    }
    normalized_events = [
        {
            key: (_number(value) if isinstance(value, Decimal) else value)
            for key, value in row.items()
        }
        for row in events
    ]
    return CapabilityResult(
        capability_id=capability_id,
        objects=[
            _object(
                "organization_company_relationship",
                properties["organization_company_relationship_id"],
                properties,
                capability_id,
            )
        ],
        outcome={
            "relationship_type": "network_edge",
            "snapshot_id": snapshot_id,
            "summary": {
                key: (_number(value) if isinstance(value, Decimal) else value)
                for key, value in summary.items()
            },
            "events": normalized_events,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "analysis_basis": {
                "event_attribution": "first_contract_date",
                "contract_amount_version": "latest_at_ledger_refresh",
                "period_from_year": inputs["period_from_year"],
                "period_to_year": inputs["period_to_year"],
                "work_type": inputs.get("work_type"),
                "field_code": inputs.get("field_code"),
                "region_basis": inputs.get("region_basis"),
                "region_code": inputs.get("region_code"),
                "region_codes": inputs.get("region_codes"),
            },
            "coverage": {
                "contract": "available",
                "award": "not_in_read_model",
                "observed_participation": "not_in_read_model",
                "region_filter": (
                    "linked_structured_bid_notice_restriction"
                    if inputs.get("region_basis")
                    else "not_requested"
                ),
            },
        },
    )
