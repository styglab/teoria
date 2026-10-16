from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)

from .cache import _cached, _store
from .filters import (
    _INITIALS,
    ENTITY_TYPES,
    _hangul_initials,
    _normalized_query,
)
from .pagination import _cursor, _decode_cursor
from .presentation import _number, _object
from .reader import ProcurementExplorationReader


async def execute_autocomplete_procurement_entities(
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
    started = time.perf_counter()
    query = _normalized_query(inputs["query"])
    if not query:
        raise CapabilityExecutionError(
            "invalid_query", "query must not be empty", capability_id=capability_id
        )
    requested = tuple(inputs.get("types") or ENTITY_TYPES)
    unknown = sorted(set(requested) - set(ENTITY_TYPES))
    if unknown:
        raise CapabilityExecutionError(
            "unsupported_entity_type",
            f"unsupported types: {', '.join(unknown)}",
            capability_id=capability_id,
        )
    limit = int(inputs.get("limit", 8))
    fingerprint = hashlib.sha256(
        json.dumps([query, sorted(requested)], ensure_ascii=False).encode()
    ).hexdigest()[:16]
    offset = _decode_cursor(inputs.get("cursor"), fingerprint, capability_id)
    scan_for_initials = bool(query) and all(
        character in _INITIALS for character in query
    )
    resolved = reader or ProcurementExplorationReader()
    try:
        rows = await resolved.autocomplete(
            catalog,
            query=query,
            entity_types=requested,
            scan_for_initials=scan_for_initials,
            fetch_limit=offset + limit + 1,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    for row in rows:
        name = str(row.get("display_name") or "")
        number = _normalized_query(row.get("display_number"))
        normalized_name = _normalized_query(name)
        initials = _hangul_initials(name)
        row["_score"] = (
            0
            if normalized_name == query or number == query
            else 1
            if normalized_name.startswith(query) or number.startswith(query)
            else 2
            if initials.startswith(query)
            else 3
        )
    if scan_for_initials:
        rows = [
            row
            for row in rows
            if _hangul_initials(str(row.get("display_name") or "")).startswith(query)
        ]
    rows.sort(
        key=lambda row: (
            row["_score"],
            str(row.get("display_name") or ""),
            str(row["entity_id"]),
        )
    )
    page = rows[offset : offset + limit]
    has_more = offset + limit < len(rows)
    candidates = []
    for row in page:
        context = dict(row.get("context") or {})
        applicable = [
            key for key in ("work_type", "field_code") if context.get(key) is not None
        ]
        if context.get("region_codes"):
            applicable.append("region")
        missing = (
            [key for key in ("work_type", "field_code") if context.get(key) is None]
            if row["entity_type"] == "bid_notice"
            else []
        )
        if row["entity_type"] == "bid_notice" and not context.get("region_codes"):
            missing.append("region")
        filter_values = (
            {
                "work_type": context.get("work_type"),
                "field_code": context.get("field_code"),
                "region": (
                    {
                        "basis": context.get("region_basis"),
                        "codes": context.get("region_codes"),
                        "match": "any",
                    }
                    if context.get("region_codes")
                    else None
                ),
            }
            if row["entity_type"] == "bid_notice"
            else None
        )
        candidates.append(
            {
                "type": row["entity_type"],
                "id": str(row["entity_id"]),
                "name": row.get("display_name"),
                "number": row.get("display_number"),
                "context": context,
                "applicable_filters": applicable,
                "filter_values": filter_values,
                "missing_filters": missing,
                "unsupported_filters": [],
            }
        )
    outcome = {
        "query": query,
        "types": list(requested),
        "candidates": candidates,
        "cursor": _cursor(offset + limit, fingerprint) if has_more else None,
        "has_more": has_more,
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        "coverage": {"source": "runtime_internal_index", "external_calls": False},
    }
    properties = {
        "procurement_entity_suggestions_id": fingerprint,
        "candidate_count": len(candidates),
    }
    return await _store(
        cache,
        cache_key,
        CapabilityResult(
            capability_id=capability_id,
            objects=[
                _object(
                    "procurement_entity_suggestions",
                    fingerprint,
                    properties,
                    capability_id,
                )
            ],
            outcome=outcome,
        ),
        300,
    )


async def execute_procurement_classification_catalog(
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
    query = str(inputs.get("query") or "").strip() or None
    limit = int(inputs.get("limit", 50))
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                query,
                inputs.get("work_type"),
                inputs.get("large_category"),
                inputs.get("middle_category"),
            ],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:16]
    offset = _decode_cursor(inputs.get("cursor"), fingerprint, capability_id)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, has_more, updated_at = await resolved.classifications(
            catalog,
            query=query,
            work_type=inputs.get("work_type"),
            large_category=inputs.get("large_category"),
            middle_category=inputs.get("middle_category"),
            offset=offset,
            limit=limit,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    items = [
        {
            key: (_number(value) if key == "observed_notice_count" else value)
            for key, value in row.items()
            if key != "updated_at"
        }
        for row in rows
    ]
    properties = {
        "procurement_classification_catalog_id": fingerprint,
        "item_count": len(items),
    }
    return await _store(
        cache,
        cache_key,
        CapabilityResult(
            capability_id=capability_id,
            objects=[
                _object(
                    "procurement_classification_catalog",
                    fingerprint,
                    properties,
                    capability_id,
                )
            ],
            outcome={
                "classification_system": "pps_procurement",
                "items": items,
                "cursor": _cursor(offset + limit, fingerprint) if has_more else None,
                "has_more": has_more,
                "updated_at": updated_at,
                "coverage": {
                    "basis": "official_classifications_observed_in_bid_notices"
                },
            },
        ),
        300,
    )


async def execute_procurement_region_filter_options(
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
    basis = str(inputs.get("region_basis") or "participation_restriction")
    if basis != "participation_restriction":
        raise CapabilityExecutionError(
            "unsupported_region_basis",
            f"unsupported region_basis '{basis}'",
            capability_id=capability_id,
        )
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, updated_at = await resolved.regions(
            catalog, query=str(inputs.get("query") or "").strip() or None
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc
    items = [
        {
            "region_code": row["region_code"],
            "region_name": row["region_name"],
            "observed_notice_count": int(row["observed_notice_count"]),
        }
        for row in rows
    ]
    properties = {
        "procurement_region_filter_options_id": basis,
        "option_count": len(items),
    }
    return await _store(
        cache,
        cache_key,
        CapabilityResult(
            capability_id=capability_id,
            objects=[
                _object(
                    "procurement_region_filter_options",
                    basis,
                    properties,
                    capability_id,
                )
            ],
            outcome={
                "region_basis": basis,
                "options": items,
                "updated_at": updated_at,
                "coverage": {
                    "basis": "structured_bid_notice_participation_regions",
                    "complete_market_coverage": False,
                },
            },
        ),
        300,
    )
