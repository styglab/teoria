from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from teoria.persistence.postgres import connect
from psycopg.rows import dict_row

from teoria.domains.public_procurement.market_analysis.related_projects.sql import (
    _COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY,
    _COMPANY_SIMILAR_PROJECT_METRICS_QUERY,
    _COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY,
    _SIMILAR_NOTICE_CANDIDATES_QUERY,
)
from teoria.registry.loader import RegistryCatalog

SIMILARITY_CANDIDATE_LIMIT = 300


class SimilarBidNoticeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        bid_notice_id: str,
        *,
        period_years: int,
        result_statuses: list[str],
        timings: dict[str, float] | None = None,
        candidate_limit: int = SIMILARITY_CANDIDATE_LIMIT,
        similarity_threshold: float = 0.15,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = bid_notice_id.rpartition(":")
        if not separator or not notice_number or not notice_order:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        async with connect(database_url, row_factory=dict_row) as connection:
            await connection.execute(
                "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                (str(similarity_threshold),),
            )
            started = time.perf_counter()
            notice = await (
                await connection.execute(
                    """
                SELECT notice_number || ':' || notice_order AS bid_notice_id,
                       notice_name, notice_published_at::date AS notice_published_date,
                       work_type, contract_method_name,
                       estimated_price, allocated_budget, demand_organization_code,
                       demand_organization_name,
                       LEAST(now(), COALESCE(bid_deadline_at, now())) AS as_of
                FROM public_procurement.bid_notices
                WHERE notice_number=%s AND notice_order=%s
                """,
                    (notice_number, notice_order),
                )
            ).fetchone()
            if timings is not None:
                timings["current_notice_lookup_ms"] = (
                    time.perf_counter() - started
                ) * 1000
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            notice["industries"] = [
                dict(row)
                for row in (
                    await (
                        await connection.execute(
                            """
                SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$')
                       AS industry_code,
                       NULLIF(regexp_replace(license_restriction_name, '/[0-9]{4}$', ''), '')
                       AS industry_name
                FROM public_procurement.bid_notice_license_restrictions
                WHERE notice_number=%s AND notice_order=%s
                  AND license_restriction_name ~ '/[0-9]{4}$'
                ORDER BY industry_code
                """,
                            tuple(str(notice["bid_notice_id"]).rsplit(":", 1)),
                        )
                    ).fetchall()
                )
            ]
            notice["industry_codes"] = [
                str(item["industry_code"]) for item in notice["industries"]
            ]
            started = time.perf_counter()
            rows = list(
                (
                    await (
                        await connection.execute(
                            _SIMILAR_NOTICE_CANDIDATES_QUERY,
                            {
                                "bid_notice_id": bid_notice_id,
                                "notice_number": notice_number,
                                "notice_order": notice_order,
                                "work_type": notice["work_type"],
                                "organization_code": notice["demand_organization_code"],
                                "as_of": notice["as_of"],
                                "period_years": period_years,
                                "include_awarded": "awarded" in result_statuses,
                                "include_contracted": "contracted" in result_statuses,
                                "candidate_limit": candidate_limit,
                            },
                        )
                    ).fetchall()
                )
            )
            if timings is not None:
                timings["market_similar_query_ms"] = (
                    time.perf_counter() - started
                ) * 1000
        return dict(notice), [dict(row) for row in rows]


class CompanySimilarProjectExperienceReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    async def find(
        self,
        catalog: RegistryCatalog,
        *,
        reference_bid_notice_id: str,
        business_registration_number: str,
        period_years: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = reference_bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        async with connect(database_url, row_factory=dict_row) as connection:
            reference = await (
                await connection.execute(
                    _COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY,
                    {"notice_number": notice_number, "notice_order": notice_order},
                )
            ).fetchone()
            if reference is None:
                raise LookupError(
                    f"bid notice '{reference_bid_notice_id}' was not found"
                )
            reference = dict(reference)
            rows = await (
                await connection.execute(
                    _COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY,
                    {
                        "notice_number": notice_number,
                        "notice_order": notice_order,
                        "company_number": business_registration_number,
                        "period_years": period_years,
                    },
                )
            ).fetchall()
        return reference, [dict(row) for row in rows]

    async def count_many(
        self,
        catalog: RegistryCatalog,
        *,
        reference_bid_notice_id: str,
        business_registration_numbers: list[str],
        period_years: int,
    ) -> dict[str, dict[str, int]]:
        if not business_registration_numbers:
            return {}
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = reference_bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        async with connect(database_url, row_factory=dict_row) as connection:
            rows = await (
                await connection.execute(
                    _COMPANY_SIMILAR_PROJECT_METRICS_QUERY,
                    {
                        "notice_number": notice_number,
                        "notice_order": notice_order,
                        "company_numbers": business_registration_numbers,
                        "period_years": period_years,
                    },
                )
            ).fetchall()
        return {
            str(row["company_number"]): {
                key: int(row[key])
                for key in (
                    "candidate_count",
                    "event_count",
                    "strong_event_count",
                    "limited_event_count",
                    "reference_only_event_count",
                    "similar_amount_event_count",
                )
            }
            for row in rows
        }
