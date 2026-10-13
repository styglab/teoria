from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

import psycopg
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


ENTITY_TYPES = ("bid_notice", "organization", "company", "classification")
WORK_TYPES = ("goods", "service", "construction", "foreign", "other", "unknown")
_INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def _digits(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _normalized_query(value: Any) -> str:
    return re.sub(r"[\s\-]+", "", str(value or "").strip().casefold())


def _hangul_initials(value: str) -> str:
    result: list[str] = []
    for character in value:
        code = ord(character)
        if 0xAC00 <= code <= 0xD7A3:
            result.append(_INITIALS[(code - 0xAC00) // 588])
        elif not character.isspace():
            result.append(character.casefold())
    return "".join(result)


def _cursor(offset: int, fingerprint: str) -> str:
    value = json.dumps({"offset": offset, "fingerprint": fingerprint}, separators=(",", ":"))
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode_cursor(value: Any, fingerprint: str, capability_id: str) -> int:
    if not value:
        return 0
    try:
        encoded = str(value)
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(decoded)
        if payload.get("fingerprint") != fingerprint:
            raise ValueError("cursor query does not match")
        offset = int(payload["offset"])
        if offset < 0:
            raise ValueError("cursor offset is negative")
        return offset
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise CapabilityExecutionError(
            "invalid_cursor", "cursor is invalid or belongs to another query",
            capability_id=capability_id,
        ) from exc


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    number = Decimal(str(value))
    return int(number) if number == number.to_integral_value() else float(number)


def _with_period(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    current_year = datetime.now(timezone.utc).year
    period_to_year = int(inputs.get("period_to_year") or current_year)
    period_from_year = int(inputs.get("period_from_year") or max(2000, period_to_year - 4))
    if period_from_year > period_to_year:
        raise CapabilityExecutionError(
            "invalid_period", "period_from_year must not exceed period_to_year",
            capability_id=capability_id,
        )
    return {**inputs, "period_from_year": period_from_year, "period_to_year": period_to_year}


def _with_region_filter(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    basis = inputs.get("region_basis")
    code = str(inputs.get("region_code") or "").strip() or None
    codes = [str(value).strip() for value in (inputs.get("region_codes") or []) if str(value).strip()]
    if code:
        codes.append(code)
    codes = list(dict.fromkeys(codes))
    if basis is not None and basis != "participation_restriction":
        raise CapabilityExecutionError(
            "unsupported_region_basis", f"unsupported region_basis '{basis}'",
            capability_id=capability_id,
        )
    if codes and basis is None:
        basis = "participation_restriction"
    return {
        **inputs, "region_basis": basis,
        "region_code": codes[0] if len(codes) == 1 else None,
        "region_codes": codes or None,
    }


class ProcurementExplorationReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def _connect(self, catalog: RegistryCatalog):
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        return psycopg.connect(database_url, row_factory=dict_row)

    def autocomplete(
        self, catalog: RegistryCatalog, *, query: str, entity_types: tuple[str, ...],
        scan_for_initials: bool, fetch_limit: int,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        number = _digits(query)
        with self._connect(catalog) as connection:
            rows = connection.execute(
                """
                SELECT entity_type,entity_id,display_name,display_number,sort_at,context
                FROM public_procurement.procurement_entity_search_index
                WHERE entity_type=ANY(%(types)s)
                  AND (CASE WHEN %(initial_search)s THEN initials LIKE %(prefix)s
                            ELSE normalized_name LIKE %(pattern)s
                              OR (%(number)s<>'' AND display_number LIKE %(number_pattern)s)
                       END)
                ORDER BY CASE WHEN normalized_name=%(query)s OR display_number=%(query)s THEN 0
                              WHEN normalized_name LIKE %(prefix)s OR display_number LIKE %(prefix)s THEN 1
                              WHEN initials LIKE %(prefix)s THEN 2 ELSE 3 END,
                         sort_at DESC NULLS LAST,display_name,entity_id
                LIMIT %(fetch_limit)s
                """,
                {"types": list(entity_types), "initial_search": scan_for_initials,
                 "query": query, "pattern": pattern, "prefix": f"{query}%",
                 "number": number, "number_pattern": f"%{number}%",
                 "fetch_limit": fetch_limit},
            ).fetchall()
            notice_numbers = sorted({
                str(row["entity_id"]).rsplit(":", 1)[0]
                for row in rows if row["entity_type"] == "bid_notice"
            })
            region_rows = [] if not notice_numbers else connection.execute(
                """
                SELECT notice_number,notice_order,participation_region_code AS region_code,
                       max(participation_region_name) AS region_name
                FROM public_procurement.bid_notice_participation_regions
                WHERE notice_number=ANY(%(notice_numbers)s)
                  AND COALESCE(participation_region_code,'') NOT IN ('','00')
                GROUP BY notice_number,notice_order,participation_region_code
                ORDER BY notice_number,notice_order,participation_region_code
                """, {"notice_numbers": notice_numbers},
            ).fetchall()
        regions_by_notice: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        for region in region_rows:
            key = (str(region["notice_number"]), str(region["notice_order"]))
            regions_by_notice.setdefault(key, []).append({
                "code": str(region["region_code"]), "name": region["region_name"],
            })
        materialized = [dict(row) for row in rows]
        for row in materialized:
            if row["entity_type"] != "bid_notice":
                continue
            notice_number, notice_order = str(row["entity_id"]).rsplit(":", 1)
            regions = regions_by_notice.get((notice_number, notice_order), [])
            context = dict(row.get("context") or {})
            context["region_basis"] = "participation_restriction" if regions else None
            context["region_conditions"] = regions or None
            context["region_codes"] = [item["code"] for item in regions] or None
            context["region_names"] = [item["name"] for item in regions] or None
            context["region_code"] = regions[0]["code"] if len(regions) == 1 else None
            context["region_name"] = regions[0]["name"] if len(regions) == 1 else None
            row["context"] = context
        return materialized

    def classifications(
        self, catalog: RegistryCatalog, *, query: str | None, work_type: str | None,
        large_category: str | None, middle_category: str | None,
        offset: int, limit: int,
    ) -> tuple[list[dict[str, Any]], bool, datetime | None]:
        with self._connect(catalog) as connection:
            rows = connection.execute(
                """
                WITH fields AS (
                  SELECT procurement_classification_number AS field_code,
                         max(procurement_classification_name) AS field_name,
                         max(procurement_large_classification_name) AS large_category,
                         max(procurement_middle_classification_name) AS middle_category,
                         array_agg(DISTINCT work_type ORDER BY work_type) AS work_types,
                         count(*) AS observed_notice_count,max(updated_at) AS updated_at
                  FROM public_procurement.bid_notices
                  WHERE procurement_classification_number IS NOT NULL
                  GROUP BY procurement_classification_number
                )
                SELECT * FROM fields
                WHERE (%(query)s::text IS NULL OR field_code ILIKE %(query_pattern)s
                       OR field_name ILIKE %(query_pattern)s)
                  AND (%(work_type)s::text IS NULL OR %(work_type)s=ANY(work_types))
                  AND (%(large_category)s::text IS NULL OR large_category=%(large_category)s)
                  AND (%(middle_category)s::text IS NULL OR middle_category=%(middle_category)s)
                ORDER BY large_category NULLS LAST,middle_category NULLS LAST,
                         field_name NULLS LAST,field_code
                OFFSET %(offset)s LIMIT %(fetch)s
                """,
                {"query": query, "query_pattern": f"%{query or ''}%", "work_type": work_type,
                 "large_category": large_category, "middle_category": middle_category,
                 "offset": offset, "fetch": limit + 1},
            ).fetchall()
        materialized = [dict(row) for row in rows]
        updated_at = max((row["updated_at"] for row in materialized), default=None)
        return materialized[:limit], len(materialized) > limit, updated_at

    def regions(self, catalog: RegistryCatalog, *, query: str | None) -> tuple[list[dict[str, Any]], datetime | None]:
        with self._connect(catalog) as connection:
            rows = connection.execute(
                """
                SELECT participation_region_code AS region_code,
                       max(participation_region_name) AS region_name,
                       count(DISTINCT (notice_number,notice_order)) AS observed_notice_count,
                       max(updated_at) AS updated_at
                FROM public_procurement.bid_notice_participation_regions
                WHERE participation_region_code IS NOT NULL
                  AND participation_region_code NOT IN ('','00')
                  AND (%(query)s::text IS NULL OR participation_region_code ILIKE %(pattern)s
                       OR participation_region_name ILIKE %(pattern)s)
                GROUP BY participation_region_code
                ORDER BY region_name,region_code
                """, {"query": query, "pattern": f"%{query or ''}%"},
            ).fetchall()
        materialized = [dict(row) for row in rows]
        return materialized, max((row["updated_at"] for row in materialized), default=None)

    @staticmethod
    def _ledger_filters(inputs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        clauses = ["first_contract_date >= make_date(%(from_year)s,1,1)",
                   "first_contract_date < make_date(%(to_year)s+1,1,1)"]
        params: dict[str, Any] = {
            "from_year": int(inputs["period_from_year"]),
            "to_year": int(inputs["period_to_year"]),
        }
        for key, column in (("field_code", "field_code"), ("work_type", "work_type")):
            if inputs.get(key):
                clauses.append(f"{column}=%({key})s")
                params[key] = str(inputs[key])
        if inputs.get("region_basis") or inputs.get("region_codes"):
            clauses.append(
                "EXISTS (SELECT 1 FROM public_procurement.bid_notice_participation_regions "
                "notice_region WHERE notice_region.notice_number=normalized_notice_number "
                "AND COALESCE(notice_region.participation_region_code,'') NOT IN ('','00') "
                "AND (%(region_codes)s::text[] IS NULL OR "
                "notice_region.participation_region_code=ANY(%(region_codes)s::text[])))"
            )
            params["region_codes"] = inputs.get("region_codes")
        return " AND ".join(clauses), params

    def ledger_snapshot(self, catalog: RegistryCatalog) -> datetime | None:
        with self._connect(catalog) as connection:
            row = connection.execute(
                "SELECT max(refreshed_at) AS snapshot_id FROM "
                "public_procurement.contract_event_company_ledger"
            ).fetchone()
        return row["snapshot_id"] if row else None

    def network_edges(
        self, catalog: RegistryCatalog, *, inputs: dict[str, Any],
        root_type: str, root_id: str, first_limit: int, second_limit: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime | None]:
        where, params = self._ledger_filters(inputs)
        aggregate = """
          SELECT organization_code,max(organization_name) AS organization_name,
                 company_number,max(company_name) AS company_name,
                 count(DISTINCT contract_event_id) AS contract_count,
                 sum(attributed_contract_amount) AS attributed_amount,
                 min(first_contract_date) AS first_contract_date,
                 max(latest_contract_version_date) AS latest_contract_date,
                 CASE WHEN count(attributed_contract_amount)=count(*) THEN 'complete'
                      WHEN count(attributed_contract_amount)=0 THEN 'unknown' ELSE 'partial' END
                   AS amount_completeness,
                 max(refreshed_at) AS updated_at
          FROM public_procurement.contract_event_company_ledger
        """
        with self._connect(catalog) as connection:
            snapshot = connection.execute(
                "SELECT max(refreshed_at) AS value FROM public_procurement.contract_event_company_ledger"
            ).fetchone()["value"]
            if root_type == "organization":
                first_params = {**params, "root_id": root_id, "limit": first_limit + 1}
                first = connection.execute(
                    aggregate + f" WHERE {where} AND organization_code=%(root_id)s "
                    "GROUP BY organization_code,company_number ORDER BY contract_count DESC,"
                    "attributed_amount DESC NULLS LAST,company_number LIMIT %(limit)s", first_params,
                ).fetchall()
                intermediate = [row["company_number"] for row in first[:first_limit]]
                second = [] if not intermediate or second_limit == 0 else connection.execute(
                    aggregate + f" WHERE {where} AND company_number=ANY(%(ids)s) "
                    "AND organization_code<>%(root_id)s GROUP BY organization_code,company_number "
                    "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                    "organization_code,company_number LIMIT %(limit)s",
                    {**params, "ids": intermediate, "root_id": root_id, "limit": second_limit + 1},
                ).fetchall()
            elif root_type == "company":
                first = connection.execute(
                    aggregate + f" WHERE {where} AND company_number=%(root_id)s "
                    "GROUP BY organization_code,company_number ORDER BY contract_count DESC,"
                    "attributed_amount DESC NULLS LAST,organization_code LIMIT %(limit)s",
                    {**params, "root_id": root_id, "limit": first_limit + 1},
                ).fetchall()
                intermediate = [row["organization_code"] for row in first[:first_limit]]
                second = [] if not intermediate or second_limit == 0 else connection.execute(
                    aggregate + f" WHERE {where} AND organization_code=ANY(%(ids)s) "
                    "AND company_number<>%(root_id)s GROUP BY organization_code,company_number "
                    "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                    "organization_code,company_number LIMIT %(limit)s",
                    {**params, "ids": intermediate, "root_id": root_id, "limit": second_limit + 1},
                ).fetchall()
            else:
                first = connection.execute(
                    aggregate + f" WHERE {where} GROUP BY organization_code,company_number "
                    "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                    "organization_code,company_number LIMIT %(limit)s",
                    {**params, "limit": first_limit + 1},
                ).fetchall()
                second = []
        return [dict(row) for row in first], [dict(row) for row in second], snapshot

    def field_market(self, catalog: RegistryCatalog, *, inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], datetime | None]:
        where, params = self._ledger_filters(inputs)
        with self._connect(catalog) as connection:
            rows = connection.execute(
                f"""
                SELECT extract(year FROM first_contract_date)::integer AS year,
                       max(field_name) AS field_name,max(large_category) AS large_category,
                       max(middle_category) AS middle_category,
                       count(DISTINCT organization_code) AS organization_count,
                       count(DISTINCT company_number) AS company_count,
                       count(DISTINCT (organization_code,contract_event_id)) AS contract_count,
                       sum(attributed_contract_amount) AS total_attributed_contract_amount,
                       count(*) FILTER (WHERE attributed_contract_amount IS NULL)
                         AS missing_attributed_amount_count,
                       max(refreshed_at) AS updated_at
                FROM public_procurement.contract_event_company_ledger
                WHERE {where}
                GROUP BY extract(year FROM first_contract_date)::integer
                ORDER BY year
                """, params,
            ).fetchall()
        materialized = [dict(row) for row in rows]
        return materialized, max((row["updated_at"] for row in materialized), default=None)

    def relationship_events(
        self, catalog: RegistryCatalog, *, inputs: dict[str, Any], offset: int, limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], datetime | None]:
        where, params = self._ledger_filters(inputs)
        params.update({
            "organization_code": str(inputs["organization_code"]),
            "company_number": _digits(inputs["business_registration_number"]),
            "offset": offset, "fetch": limit,
        })
        scope = where + " AND organization_code=%(organization_code)s AND company_number=%(company_number)s"
        with self._connect(catalog) as connection:
            snapshot = connection.execute(
                "SELECT max(refreshed_at) AS value FROM public_procurement.contract_event_company_ledger"
            ).fetchone()["value"]
            summary = dict(connection.execute(
                f"""
                SELECT count(DISTINCT contract_event_id) AS contract_count,
                       sum(attributed_contract_amount) AS total_attributed_contract_amount,
                       min(first_contract_date) AS first_contract_date,
                       max(latest_contract_version_date) AS latest_contract_date,
                       sum(contract_version_count) AS contract_version_count,
                       count(*) FILTER (WHERE attributed_contract_amount IS NULL)
                         AS missing_attributed_amount_count
                FROM public_procurement.contract_event_company_ledger WHERE {scope}
                """, params,
            ).fetchone())
            rows = connection.execute(
                f"""
                SELECT contract_event_id,unified_contract_number,contract_name,
                       first_contract_date,latest_contract_version_date,contract_version_count,
                       work_type,field_code,field_name,large_category,middle_category,
                       company_role,share_percent,attributed_contract_amount,
                       amount_completeness,contract_amount,normalized_notice_number
                FROM public_procurement.contract_event_company_ledger WHERE {scope}
                ORDER BY first_contract_date DESC,contract_event_id
                OFFSET %(offset)s LIMIT %(fetch)s
                """, params,
            ).fetchall()
        return [dict(row) for row in rows], summary, snapshot


def _provenance(operation: str, keys: Iterable[str]) -> Provenance:
    return Provenance(
        kind="execution", source="teoria_runtime", operation=operation,
        mapping="public_procurement_exploration", observed_at=datetime.now(timezone.utc),
        record_keys=list(keys),
    )


def _object(object_type: str, object_id: str, properties: dict[str, Any], operation: str) -> MaterializedObject:
    provenance = _provenance(operation, [object_id])
    return MaterializedObject(
        ontology="public_procurement", object_type=object_type, object_id=object_id,
        properties=properties, provenance=[provenance],
        property_provenance={key: [provenance] for key in properties},
    )


async def _cached(cache: Any | None, catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any]) -> tuple[Any, CapabilityResult | None]:
    if cache is None:
        return None, None
    version = catalog.release.version if catalog.release else "unpublished"
    key = cache.key(version, capability_id, inputs)
    return key, await cache.get(key)


async def _store(cache: Any | None, key: Any, result: CapabilityResult, ttl: int = 60) -> CapabilityResult:
    if cache is not None:
        await cache.set(key, result, ttl)
    return result


async def execute_autocomplete_procurement_entities(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    started = time.perf_counter()
    query = _normalized_query(inputs["query"])
    if not query:
        raise CapabilityExecutionError("invalid_query", "query must not be empty", capability_id=capability_id)
    requested = tuple(inputs.get("types") or ENTITY_TYPES)
    unknown = sorted(set(requested) - set(ENTITY_TYPES))
    if unknown:
        raise CapabilityExecutionError("unsupported_entity_type", f"unsupported types: {', '.join(unknown)}", capability_id=capability_id)
    limit = int(inputs.get("limit", 8))
    fingerprint = hashlib.sha256(json.dumps([query, sorted(requested)], ensure_ascii=False).encode()).hexdigest()[:16]
    offset = _decode_cursor(inputs.get("cursor"), fingerprint, capability_id)
    scan_for_initials = bool(query) and all(character in _INITIALS for character in query)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows = await asyncio.to_thread(
            resolved.autocomplete, catalog, query=query, entity_types=requested,
            scan_for_initials=scan_for_initials, fetch_limit=offset + limit + 1,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    for row in rows:
        name = str(row.get("display_name") or "")
        number = _normalized_query(row.get("display_number"))
        normalized_name = _normalized_query(name)
        initials = _hangul_initials(name)
        row["_score"] = (
            0 if normalized_name == query or number == query else
            1 if normalized_name.startswith(query) or number.startswith(query) else
            2 if initials.startswith(query) else 3
        )
    if scan_for_initials:
        rows = [row for row in rows if _hangul_initials(str(row.get("display_name") or "")).startswith(query)]
    rows.sort(key=lambda row: (row["_score"], str(row.get("display_name") or ""), str(row["entity_id"])))
    page = rows[offset:offset + limit]
    has_more = offset + limit < len(rows)
    candidates = []
    for row in page:
        context = dict(row.get("context") or {})
        applicable = [key for key in ("work_type", "field_code") if context.get(key) is not None]
        if context.get("region_codes"):
            applicable.append("region")
        missing = [key for key in ("work_type", "field_code") if context.get(key) is None] if row["entity_type"] == "bid_notice" else []
        if row["entity_type"] == "bid_notice" and not context.get("region_codes"):
            missing.append("region")
        filter_values = {
            "work_type": context.get("work_type"),
            "field_code": context.get("field_code"),
            "region": ({
                "basis": context.get("region_basis"),
                "codes": context.get("region_codes"),
                "match": "any",
            } if context.get("region_codes") else None),
        } if row["entity_type"] == "bid_notice" else None
        candidates.append({
            "type": row["entity_type"], "id": str(row["entity_id"]),
            "name": row.get("display_name"), "number": row.get("display_number"),
            "context": context, "applicable_filters": applicable,
            "filter_values": filter_values,
            "missing_filters": missing, "unsupported_filters": [],
        })
    outcome = {
        "query": query, "types": list(requested), "candidates": candidates,
        "cursor": _cursor(offset + limit, fingerprint) if has_more else None,
        "has_more": has_more, "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        "coverage": {"source": "runtime_internal_index", "external_calls": False},
    }
    properties = {"procurement_entity_suggestions_id": fingerprint, "candidate_count": len(candidates)}
    return await _store(cache, cache_key, CapabilityResult(capability_id=capability_id,
        objects=[_object("procurement_entity_suggestions", fingerprint, properties, capability_id)], outcome=outcome), 300)


async def execute_procurement_classification_catalog(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    query = str(inputs.get("query") or "").strip() or None
    limit = int(inputs.get("limit", 50))
    fingerprint = hashlib.sha256(json.dumps([query, inputs.get("work_type"), inputs.get("large_category"), inputs.get("middle_category")], ensure_ascii=False).encode()).hexdigest()[:16]
    offset = _decode_cursor(inputs.get("cursor"), fingerprint, capability_id)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, has_more, updated_at = await asyncio.to_thread(
            resolved.classifications, catalog, query=query, work_type=inputs.get("work_type"),
            large_category=inputs.get("large_category"), middle_category=inputs.get("middle_category"),
            offset=offset, limit=limit,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    items = [{key: (_number(value) if key == "observed_notice_count" else value)
              for key, value in row.items() if key != "updated_at"} for row in rows]
    properties = {"procurement_classification_catalog_id": fingerprint, "item_count": len(items)}
    return await _store(cache, cache_key, CapabilityResult(capability_id=capability_id,
        objects=[_object("procurement_classification_catalog", fingerprint, properties, capability_id)],
        outcome={"classification_system": "pps_procurement", "items": items,
                 "cursor": _cursor(offset + limit, fingerprint) if has_more else None,
                 "has_more": has_more, "updated_at": updated_at,
                 "coverage": {"basis": "official_classifications_observed_in_bid_notices"}}), 300)


async def execute_procurement_region_filter_options(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    basis = str(inputs.get("region_basis") or "participation_restriction")
    if basis != "participation_restriction":
        raise CapabilityExecutionError("unsupported_region_basis", f"unsupported region_basis '{basis}'", capability_id=capability_id)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, updated_at = await asyncio.to_thread(resolved.regions, catalog, query=str(inputs.get("query") or "").strip() or None)
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    items = [{"region_code": row["region_code"], "region_name": row["region_name"],
              "observed_notice_count": int(row["observed_notice_count"])} for row in rows]
    properties = {"procurement_region_filter_options_id": basis, "option_count": len(items)}
    return await _store(cache, cache_key, CapabilityResult(capability_id=capability_id,
        objects=[_object("procurement_region_filter_options", basis, properties, capability_id)],
        outcome={"region_basis": basis, "options": items, "updated_at": updated_at,
                 "coverage": {"basis": "structured_bid_notice_participation_regions", "complete_market_coverage": False}}), 300)


def _edge(row: dict[str, Any], *, hop: int) -> dict[str, Any]:
    return {
        "id": f"organization:{row['organization_code']}|company:{row['company_number']}",
        "source": {"type": "organization", "id": str(row["organization_code"])},
        "target": {"type": "company", "id": str(row["company_number"])},
        "hop": hop,
        "relationships": {
            "contract": {
                "event_count": int(row["contract_count"]),
                "attributed_amount": _number(row.get("attributed_amount")),
                "amount_completeness": row.get("amount_completeness"),
                "first_contract_date": row.get("first_contract_date"),
                "latest_contract_date": row.get("latest_contract_date"),
            },
            "award": None, "observed_participation": None,
            "co_participation": None, "joint_contract": None,
        },
    }


async def execute_procurement_network(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    inputs = _with_region_filter(_with_period(inputs, capability_id), capability_id)
    root_type = str(inputs.get("root_type") or ("field" if inputs.get("field_code") else ""))
    root_id = str(inputs.get("root_id") or inputs.get("field_code") or "").strip()
    if root_type not in {"organization", "company", "field"} or not root_id:
        raise CapabilityExecutionError("invalid_root", "root_type/root_id or field_code is required", capability_id=capability_id)
    if root_type == "field":
        inputs = {**inputs, "field_code": root_id}
    depth = int(inputs.get("depth", 1))
    first_limit = int(inputs.get("first_hop_limit", 20))
    second_limit = int(inputs.get("second_hop_limit", 50)) if depth == 2 else 0
    resolved = reader or ProcurementExplorationReader()
    try:
        first, second, snapshot = await asyncio.to_thread(
            resolved.network_edges, catalog, inputs=inputs, root_type=root_type,
            root_id=root_id, first_limit=first_limit, second_limit=second_limit,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    first_truncated = len(first) > first_limit
    second_truncated = len(second) > second_limit if second_limit else False
    edge_rows = [(row, 1) for row in first[:first_limit]] + [(row, 2) for row in second[:second_limit]]
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    if root_type == "field":
        nodes[("field", root_id)] = {"type": "field", "id": root_id, "name": next((row.get("field_name") for row in first if row.get("field_name")), None), "is_root": True}
    for row, _ in edge_rows:
        nodes[("organization", str(row["organization_code"]))] = {
            "type": "organization", "id": str(row["organization_code"]),
            "name": row.get("organization_name"),
            "is_root": root_type == "organization" and str(row["organization_code"]) == root_id,
        }
        nodes[("company", str(row["company_number"]))] = {
            "type": "company", "id": str(row["company_number"]),
            "name": row.get("company_name"),
            "is_root": root_type == "company" and str(row["company_number"]) == root_id,
        }
    edges = [_edge(row, hop=hop) for row, hop in edge_rows]
    total_contracts = sum(edge["relationships"]["contract"]["event_count"] for edge in edges)
    snapshot_id = snapshot.isoformat() if snapshot else None
    properties = {"procurement_network_id": hashlib.sha256(json.dumps([root_type, root_id, snapshot_id]).encode()).hexdigest()[:24],
                  "node_count": len(nodes), "edge_count": len(edges)}
    return await _store(cache, cache_key, CapabilityResult(capability_id=capability_id,
        objects=[_object("procurement_network", properties["procurement_network_id"], properties, capability_id)],
        outcome={
            "root": {"type": root_type, "id": root_id}, "snapshot_id": snapshot_id,
            "nodes": list(nodes.values()), "edges": edges,
            "summary": {"node_count": len(nodes), "edge_count": len(edges), "contract_event_count": total_contracts},
            "truncation": {"truncated": first_truncated or second_truncated,
                           "first_hop_truncated": first_truncated, "second_hop_truncated": second_truncated,
                           "omitted_node_count": None if first_truncated or second_truncated else 0,
                           "omitted_edge_count": None if first_truncated or second_truncated else 0,
                           "selection_basis": "contract_count_desc_attributed_amount_desc"},
            "coverage": {"contract": "available", "award": "not_in_read_model",
                         "observed_participation": "not_in_read_model", "co_participation": "not_in_read_model",
                         "joint_contract": "not_in_read_model",
                         "region_filter": ("linked_structured_bid_notice_restriction"
                                           if inputs.get("region_basis") else "not_requested")},
            "analysis_basis": {"contract_date": "first_contract_date",
                               "contract_amount": "latest_version_at_ledger_refresh",
                               "period_from_year": inputs["period_from_year"],
                               "period_to_year": inputs["period_to_year"],
                               "work_type": inputs.get("work_type"), "field_code": inputs.get("field_code"),
                               "region_basis": inputs.get("region_basis"),
                               "region_code": inputs.get("region_code"),
                               "region_codes": inputs.get("region_codes")},
            "updated_at": snapshot,
        }), 60)


async def execute_procurement_field_market(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    cache_key, cached = await _cached(cache, catalog, capability_id, inputs)
    if cached is not None:
        return cached
    inputs = _with_region_filter(_with_period(inputs, capability_id), capability_id)
    resolved = reader or ProcurementExplorationReader()
    try:
        rows, updated_at = await asyncio.to_thread(resolved.field_market, catalog, inputs=inputs)
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    yearly = [{key: (_number(value) if isinstance(value, Decimal) else value)
               for key, value in row.items() if key != "updated_at"} for row in rows]
    summary = {
        "contract_count": sum(int(row["contract_count"]) for row in rows),
        "total_attributed_contract_amount": _number(sum((row["total_attributed_contract_amount"] or Decimal("0") for row in rows), Decimal("0"))) if rows else None,
        "missing_attributed_amount_count": sum(int(row["missing_attributed_amount_count"]) for row in rows),
        "organization_count": None, "company_count": None,
    }
    properties = {"procurement_field_market_id": f"{inputs['field_code']}:{inputs['period_from_year']}:{inputs['period_to_year']}",
                  "contract_count": summary["contract_count"]}
    return await _store(cache, cache_key, CapabilityResult(capability_id=capability_id,
        objects=[_object("procurement_field_market", properties["procurement_field_market_id"], properties, capability_id)],
        outcome={"field_code": inputs["field_code"], "summary": summary, "yearly": yearly,
                 "updated_at": updated_at,
                 "analysis_basis": {"scope": "runtime_collected_contract_ledger",
                                    "contract_date": "first_contract_date",
                                    "amount": "attributed_latest_contract_amount",
                                    "period_from_year": inputs["period_from_year"],
                                    "period_to_year": inputs["period_to_year"],
                                    "work_type": inputs.get("work_type"),
                                    "region_basis": inputs.get("region_basis"),
                                    "region_code": inputs.get("region_code"),
                                    "region_codes": inputs.get("region_codes")},
                 "coverage": {"is_full_market": False, "sample": True,
                              "missing_amount_count": summary["missing_attributed_amount_count"],
                              "region_filter": ("linked_structured_bid_notice_restriction"
                                                if inputs.get("region_basis") else "not_requested")}}), 60)


async def execute_network_organization_company_relationship(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any],
    *, reader: ProcurementExplorationReader | None = None,
) -> CapabilityResult:
    inputs = _with_region_filter(_with_period(inputs, capability_id), capability_id)
    resolved = reader or ProcurementExplorationReader()
    page = int(inputs.get("page", 1)); page_size = int(inputs.get("page_size", 20))
    try:
        events, summary, snapshot = await asyncio.to_thread(
            resolved.relationship_events, catalog, inputs=inputs,
            offset=(page - 1) * page_size, limit=page_size,
        )
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    snapshot_id = snapshot.isoformat() if snapshot else None
    if inputs.get("snapshot_id") and str(inputs["snapshot_id"]) != snapshot_id:
        raise CapabilityExecutionError("stale_snapshot", "requested network snapshot is no longer available", capability_id=capability_id)
    total = int(summary.get("contract_count") or 0)
    properties = {"organization_company_relationship_id": f"{inputs['organization_code']}:{_digits(inputs['business_registration_number'])}",
                  "organization_code": inputs["organization_code"],
                  "company_number": _digits(inputs["business_registration_number"]),
                  "award_event_count": 0, "unique_project_count": total,
                  "contract_event_count": total,
                  "contract_version_count": int(summary.get("contract_version_count") or 0)}
    normalized_events = [{key: (_number(value) if isinstance(value, Decimal) else value) for key, value in row.items()} for row in events]
    return CapabilityResult(capability_id=capability_id,
        objects=[_object("organization_company_relationship", properties["organization_company_relationship_id"], properties, capability_id)],
        outcome={"relationship_type": "network_edge", "snapshot_id": snapshot_id,
                 "summary": {key: (_number(value) if isinstance(value, Decimal) else value) for key, value in summary.items()},
                 "events": normalized_events,
                 "pagination": {"page": page, "page_size": page_size, "total_items": total,
                                "total_pages": (total + page_size - 1) // page_size},
                 "analysis_basis": {"event_attribution": "first_contract_date",
                                    "contract_amount_version": "latest_at_ledger_refresh",
                                    "period_from_year": inputs["period_from_year"],
                                    "period_to_year": inputs["period_to_year"],
                                    "work_type": inputs.get("work_type"), "field_code": inputs.get("field_code"),
                                    "region_basis": inputs.get("region_basis"),
                                    "region_code": inputs.get("region_code"),
                                    "region_codes": inputs.get("region_codes")},
                 "coverage": {"contract": "available", "award": "not_in_read_model",
                              "observed_participation": "not_in_read_model",
                              "region_filter": ("linked_structured_bid_notice_restriction"
                                                if inputs.get("region_basis") else "not_requested")}})
