from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Mapping

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog

from .filters import _digits


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
        return connect(database_url, row_factory=dict_row)

    async def autocomplete(
        self,
        catalog: RegistryCatalog,
        *,
        query: str,
        entity_types: tuple[str, ...],
        scan_for_initials: bool,
        fetch_limit: int,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        number = _digits(query)
        async with self._connect(catalog) as connection:
            rows = await (
                await connection.execute(
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
                    {
                        "types": list(entity_types),
                        "initial_search": scan_for_initials,
                        "query": query,
                        "pattern": pattern,
                        "prefix": f"{query}%",
                        "number": number,
                        "number_pattern": f"%{number}%",
                        "fetch_limit": fetch_limit,
                    },
                )
            ).fetchall()
            notice_numbers = sorted(
                {
                    str(row["entity_id"]).rsplit(":", 1)[0]
                    for row in rows
                    if row["entity_type"] == "bid_notice"
                }
            )
            region_rows = (
                []
                if not notice_numbers
                else (
                    await (
                        await connection.execute(
                            """
                SELECT notice_number,notice_order,participation_region_code AS region_code,
                       max(participation_region_name) AS region_name
                FROM public_procurement.bid_notice_participation_regions
                WHERE notice_number=ANY(%(notice_numbers)s)
                  AND COALESCE(participation_region_code,'') NOT IN ('','00')
                GROUP BY notice_number,notice_order,participation_region_code
                ORDER BY notice_number,notice_order,participation_region_code
                """,
                            {"notice_numbers": notice_numbers},
                        )
                    ).fetchall()
                )
            )
        regions_by_notice: dict[tuple[str, str], list[dict[str, str | None]]] = {}
        for region in region_rows:
            key = (str(region["notice_number"]), str(region["notice_order"]))
            regions_by_notice.setdefault(key, []).append(
                {
                    "code": str(region["region_code"]),
                    "name": region["region_name"],
                }
            )
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

    async def classifications(
        self,
        catalog: RegistryCatalog,
        *,
        query: str | None,
        work_type: str | None,
        large_category: str | None,
        middle_category: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool, datetime | None]:
        async with self._connect(catalog) as connection:
            rows = await (
                await connection.execute(
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
                    {
                        "query": query,
                        "query_pattern": f"%{query or ''}%",
                        "work_type": work_type,
                        "large_category": large_category,
                        "middle_category": middle_category,
                        "offset": offset,
                        "fetch": limit + 1,
                    },
                )
            ).fetchall()
        materialized = [dict(row) for row in rows]
        updated_at = max((row["updated_at"] for row in materialized), default=None)
        return materialized[:limit], len(materialized) > limit, updated_at

    async def regions(
        self, catalog: RegistryCatalog, *, query: str | None
    ) -> tuple[list[dict[str, Any]], datetime | None]:
        async with self._connect(catalog) as connection:
            rows = await (
                await connection.execute(
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
                """,
                    {"query": query, "pattern": f"%{query or ''}%"},
                )
            ).fetchall()
        materialized = [dict(row) for row in rows]
        return materialized, max(
            (row["updated_at"] for row in materialized), default=None
        )

    @staticmethod
    def _ledger_filters(inputs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        clauses = [
            "first_contract_date >= make_date(%(from_year)s,1,1)",
            "first_contract_date < make_date(%(to_year)s+1,1,1)",
        ]
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

    async def ledger_snapshot(self, catalog: RegistryCatalog) -> datetime | None:
        async with self._connect(catalog) as connection:
            row = await (
                await connection.execute(
                    "SELECT max(refreshed_at) AS snapshot_id FROM "
                    "public_procurement.contract_event_company_ledger"
                )
            ).fetchone()
        return row["snapshot_id"] if row else None

    async def network_edges(
        self,
        catalog: RegistryCatalog,
        *,
        inputs: dict[str, Any],
        root_type: str,
        root_id: str,
        first_limit: int,
        second_limit: int,
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
        async with self._connect(catalog) as connection:
            snapshot = (
                await (
                    await connection.execute(
                        "SELECT max(refreshed_at) AS value FROM public_procurement.contract_event_company_ledger"
                    )
                ).fetchone()
            )["value"]
            if root_type == "organization":
                first_params = {**params, "root_id": root_id, "limit": first_limit + 1}
                first = await (
                    await connection.execute(
                        aggregate + f" WHERE {where} AND organization_code=%(root_id)s "
                        "GROUP BY organization_code,company_number ORDER BY contract_count DESC,"
                        "attributed_amount DESC NULLS LAST,company_number LIMIT %(limit)s",
                        first_params,
                    )
                ).fetchall()
                intermediate = [row["company_number"] for row in first[:first_limit]]
                second = (
                    []
                    if not intermediate or second_limit == 0
                    else (
                        await (
                            await connection.execute(
                                aggregate
                                + f" WHERE {where} AND company_number=ANY(%(ids)s) "
                                "AND organization_code<>%(root_id)s GROUP BY organization_code,company_number "
                                "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                                "organization_code,company_number LIMIT %(limit)s",
                                {
                                    **params,
                                    "ids": intermediate,
                                    "root_id": root_id,
                                    "limit": second_limit + 1,
                                },
                            )
                        ).fetchall()
                    )
                )
            elif root_type == "company":
                first = await (
                    await connection.execute(
                        aggregate + f" WHERE {where} AND company_number=%(root_id)s "
                        "GROUP BY organization_code,company_number ORDER BY contract_count DESC,"
                        "attributed_amount DESC NULLS LAST,organization_code LIMIT %(limit)s",
                        {**params, "root_id": root_id, "limit": first_limit + 1},
                    )
                ).fetchall()
                intermediate = [row["organization_code"] for row in first[:first_limit]]
                second = (
                    []
                    if not intermediate or second_limit == 0
                    else (
                        await (
                            await connection.execute(
                                aggregate
                                + f" WHERE {where} AND organization_code=ANY(%(ids)s) "
                                "AND company_number<>%(root_id)s GROUP BY organization_code,company_number "
                                "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                                "organization_code,company_number LIMIT %(limit)s",
                                {
                                    **params,
                                    "ids": intermediate,
                                    "root_id": root_id,
                                    "limit": second_limit + 1,
                                },
                            )
                        ).fetchall()
                    )
                )
            else:
                first = await (
                    await connection.execute(
                        aggregate
                        + f" WHERE {where} GROUP BY organization_code,company_number "
                        "ORDER BY contract_count DESC,attributed_amount DESC NULLS LAST,"
                        "organization_code,company_number LIMIT %(limit)s",
                        {**params, "limit": first_limit + 1},
                    )
                ).fetchall()
                second = []
        return [dict(row) for row in first], [dict(row) for row in second], snapshot

    async def field_market(
        self, catalog: RegistryCatalog, *, inputs: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], datetime | None]:
        where, params = self._ledger_filters(inputs)
        async with self._connect(catalog) as connection:
            rows = await (
                await connection.execute(
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
                """,
                    params,
                )
            ).fetchall()
        materialized = [dict(row) for row in rows]
        return materialized, max(
            (row["updated_at"] for row in materialized), default=None
        )

    async def relationship_events(
        self,
        catalog: RegistryCatalog,
        *,
        inputs: dict[str, Any],
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], datetime | None]:
        where, params = self._ledger_filters(inputs)
        params.update(
            {
                "organization_code": str(inputs["organization_code"]),
                "company_number": _digits(inputs["business_registration_number"]),
                "offset": offset,
                "fetch": limit,
            }
        )
        scope = (
            where
            + " AND organization_code=%(organization_code)s AND company_number=%(company_number)s"
        )
        async with self._connect(catalog) as connection:
            snapshot = (
                await (
                    await connection.execute(
                        "SELECT max(refreshed_at) AS value FROM public_procurement.contract_event_company_ledger"
                    )
                ).fetchone()
            )["value"]
            summary = dict(
                (
                    await (
                        await connection.execute(
                            f"""
                SELECT count(DISTINCT contract_event_id) AS contract_count,
                       sum(attributed_contract_amount) AS total_attributed_contract_amount,
                       min(first_contract_date) AS first_contract_date,
                       max(latest_contract_version_date) AS latest_contract_date,
                       sum(contract_version_count) AS contract_version_count,
                       count(*) FILTER (WHERE attributed_contract_amount IS NULL)
                         AS missing_attributed_amount_count
                FROM public_procurement.contract_event_company_ledger WHERE {scope}
                """,
                            params,
                        )
                    ).fetchone()
                )
            )
            rows = await (
                await connection.execute(
                    f"""
                SELECT contract_event_id,unified_contract_number,contract_name,
                       first_contract_date,latest_contract_version_date,contract_version_count,
                       work_type,field_code,field_name,large_category,middle_category,
                       company_role,share_percent,attributed_contract_amount,
                       amount_completeness,contract_amount,normalized_notice_number
                FROM public_procurement.contract_event_company_ledger WHERE {scope}
                ORDER BY first_contract_date DESC,contract_event_id
                OFFSET %(offset)s LIMIT %(fetch)s
                """,
                    params,
                )
            ).fetchall()
        return [dict(row) for row in rows], summary, snapshot
