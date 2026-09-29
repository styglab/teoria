from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.assessment.models import CompanyEvidenceSnapshot, requirement_value
from teoria.runtime.assessment.processor import evaluate_requirement_category
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance


SIGNAL_POLICY_VERSION = "1.0.0"
RECENT_ACTIVITY_DAYS = 365
RELEVANCE_PROCESSOR_ID = "market_context.find_bid_relevant_companies"
RELEVANCE_PROFILE = "provided_similar_bid_notices_v1"
RELEVANCE_RANKING_PROFILE = "organization_relationship_first_v1"
SIMILARITY_PROFILE = "bid_comparison_v1"
SIMILARITY_CANDIDATE_LIMIT = 300
TITLE_TRIGRAM_SIMILARITY_THRESHOLD = 0.08
ORGANIZATION_FIELD_CACHE_TTL_SECONDS = 600
_ORGANIZATION_FIELD_CACHE: dict[tuple[str, int, int, str], tuple[float, CapabilityResult]] = {}
_ORGANIZATION_COMPANY_FIELD_CACHE: dict[tuple[Any, ...], tuple[float, CapabilityResult]] = {}


class BidCompetitorCandidateReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find_relevant(
        self,
        catalog: RegistryCatalog,
        bid_notice_id: str,
        similar_bid_notice_ids: list[str],
        *,
        limit: int,
        timings: dict[str, float] | None = None,
        award_contract_only: bool = False,
    ) -> tuple[
        dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
    ]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_pairs = []
        for value in similar_bid_notice_ids:
            notice_number, separator, notice_order = value.rpartition(":")
            if not separator or not notice_number or not notice_order:
                raise ValueError(f"invalid bid notice id '{value}'")
            notice_pairs.append({
                "bid_notice_id": value,
                "notice_number": notice_number,
                "notice_order": notice_order,
            })
        current_notice_number, separator, current_notice_order = bid_notice_id.rpartition(":")
        if not separator or not current_notice_number or not current_notice_order:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            notice = connection.execute(
                """
                SELECT bid_notice_id, notice_number, notice_order, work_type,
                       demand_organization_code, demand_organization_name,
                       requirement_expression, extraction_completeness,
                       bid_deadline_at,
                       LEAST(now(), COALESCE(bid_deadline_at, now())) AS as_of
                FROM public_procurement.runtime_bid_notices
                WHERE notice_number=%s AND notice_order=%s
                """,
                (current_notice_number, current_notice_order),
            ).fetchone()
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            if not notice["demand_organization_code"]:
                raise ValueError(f"bid notice '{bid_notice_id}' has no demand organization code")
            regions = [] if award_contract_only else list(connection.execute(
                """
                SELECT DISTINCT region_code, region_name, business_type_name
                FROM (
                    SELECT participation_region_code AS region_code,
                           participation_region_name AS region_name,
                           business_type_name
                    FROM public_procurement.bid_notice_participation_regions
                    WHERE notice_number=%s AND notice_order=%s
                    UNION ALL
                    SELECT participation_restriction_region_code,
                           participation_restriction_region_name,
                           NULL::text
                    FROM public_procurement.bid_notices
                    WHERE notice_number=%s AND notice_order=%s
                      AND participation_restriction_region_code NOT IN ('', '00')
                ) regions
                WHERE COALESCE(region_code, region_name) IS NOT NULL
                ORDER BY region_code NULLS LAST, region_name NULLS LAST
                """,
                (notice["notice_number"], notice["notice_order"],
                 notice["notice_number"], notice["notice_order"]),
            ).fetchall())
            requirements = [] if award_contract_only else list(connection.execute(
                """
                SELECT requirement_id, bid_notice_id, local_id, requirement_type,
                       value_text, original_text, mandatory, review_status,
                       assessment_stage, standard_rule_id, standard_rule_version,
                       rule_arguments_text
                FROM public_procurement.runtime_bid_requirements
                WHERE bid_notice_id=%s AND (
                    requirement_type='industry_license'
                    OR standard_rule_id='has_registered_industry'
                )
                ORDER BY local_id
                """,
                (bid_notice_id,),
            ).fetchall())
            started = time.perf_counter()
            rows = list(connection.execute(
                _RELEVANT_COMPANY_QUERY,
                {
                    "similar_notices": json.dumps(notice_pairs),
                    "organization_code": notice["demand_organization_code"],
                    "as_of": notice["as_of"],
                    "limit": limit,
                },
            ).fetchall())
            if timings is not None:
                timings["organization_history_query_ms"] = (
                    time.perf_counter() - started
                ) * 1000
            company_numbers = [str(row["company_number"]) for row in rows]
            activity_rows = list(connection.execute(
                _RELEVANT_COMPANY_ACTIVITIES_QUERY,
                {
                    "similar_notices": json.dumps(notice_pairs),
                    "company_numbers": company_numbers,
                    "as_of": notice["as_of"],
                },
            ).fetchall()) if company_numbers else []
            organization_activity_rows = list(connection.execute(
                (_ORGANIZATION_AWARD_CONTRACT_ACTIVITIES_QUERY if award_contract_only
                 else _ORGANIZATION_RELATIONSHIP_ACTIVITIES_QUERY),
                {
                    "organization_code": notice["demand_organization_code"],
                    "company_numbers": company_numbers,
                    "as_of": notice["as_of"],
                },
            ).fetchall()) if company_numbers else []
            activities_by_company: dict[str, list[dict[str, Any]]] = {}
            for activity in activity_rows:
                activities_by_company.setdefault(
                    str(activity["company_number"]), [],
                ).append({
                    key: value for key, value in dict(activity).items()
                    if key != "company_number"
                })
            organization_activities_by_company: dict[str, list[dict[str, Any]]] = {}
            for activity in organization_activity_rows:
                organization_activities_by_company.setdefault(
                    str(activity["company_number"]), [],
                ).append({
                    key: value for key, value in dict(activity).items()
                    if key != "company_number"
                })
            for row in rows:
                row["similar_activities"] = activities_by_company.get(
                    str(row["company_number"]), [],
                )
                row["organization_activities"] = organization_activities_by_company.get(
                    str(row["company_number"]), [],
                )
        return (
            dict(notice), rows, [dict(item) for item in regions],
            [dict(item) for item in requirements],
        )


class SimilarBidNoticeReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, bid_notice_id: str, *, period_years: int,
        result_statuses: list[str], timings: dict[str, float] | None = None,
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
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT set_config('pg_trgm.similarity_threshold', %s, true)",
                (str(similarity_threshold),),
            )
            started = time.perf_counter()
            notice = connection.execute(
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
            ).fetchone()
            if timings is not None:
                timings["current_notice_lookup_ms"] = (time.perf_counter() - started) * 1000
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            notice["industries"] = [dict(row) for row in connection.execute(
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
            ).fetchall()]
            notice["industry_codes"] = [
                str(item["industry_code"]) for item in notice["industries"]
            ]
            started = time.perf_counter()
            rows = list(connection.execute(
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
            ).fetchall())
            if timings is not None:
                timings["market_similar_query_ms"] = (time.perf_counter() - started) * 1000
        return dict(notice), [dict(row) for row in rows]


class OrganizationFieldEventReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, organization_code: str,
        work_type: str | None, as_of: datetime,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            return [dict(row) for row in connection.execute(
                _ORGANIZATION_FIELD_EVENT_ROWS_QUERY,
                {
                    "organization_code": organization_code,
                    "work_type": work_type,
                    "as_of": as_of,
                },
            ).fetchall()]

    def context(
        self, catalog: RegistryCatalog, *, organization_code: str,
        business_registration_number: str, reference_bid_notice_id: str | None,
    ) -> dict[str, Any]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        reference_number = reference_order = None
        if reference_bid_notice_id:
            reference_number, separator, reference_order = reference_bid_notice_id.rpartition(":")
            if not separator:
                raise ValueError(f"invalid bid notice id '{reference_bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            organization = connection.execute(
                "SELECT organization_code,organization_name FROM "
                "public_procurement.public_organizations WHERE organization_code=%s",
                (organization_code,),
            ).fetchone()
            company = connection.execute(
                "SELECT %s::text AS business_registration_number,company_name FROM ("
                "SELECT winner_name AS company_name,updated_at FROM public_procurement.bid_awards "
                "WHERE winner_business_registration_number=%s UNION ALL "
                "SELECT supplier_name,updated_at FROM public_procurement.contract_suppliers "
                "WHERE business_registration_number=%s) names "
                "WHERE company_name IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (business_registration_number, business_registration_number,
                 business_registration_number),
            ).fetchone()
            reference = None
            if reference_number and reference_order:
                reference = connection.execute(
                    "SELECT notice_number||':'||notice_order AS bid_notice_id,notice_name,work_type,"
                    "estimated_price,allocated_budget,demand_organization_code,"
                    "demand_organization_name,LEAST(now(),COALESCE(bid_deadline_at,now())) AS as_of "
                    "FROM public_procurement.bid_notices WHERE notice_number=%s AND notice_order=%s",
                    (reference_number, reference_order),
                ).fetchone()
                if reference is None:
                    raise LookupError(f"bid notice '{reference_bid_notice_id}' was not found")
                reference = dict(reference)
                reference["industry_codes"] = [str(row["industry_code"]) for row in connection.execute(
                    "SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$') "
                    "AS industry_code "
                    "FROM public_procurement.bid_notice_license_restrictions "
                    "WHERE notice_number=%s AND notice_order=%s "
                    "AND license_restriction_name~'/[0-9]{4}$'",
                    (reference_number, reference_order),
                ).fetchall()]
        return {
            "organization": dict(organization) if organization else {
                "organization_code": organization_code, "organization_name": None,
            },
            "company": dict(company) if company else {
                "business_registration_number": business_registration_number,
                "company_name": None,
            },
            "reference_notice": reference,
        }


class CompanySimilarProjectExperienceReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def find(
        self, catalog: RegistryCatalog, *, reference_bid_notice_id: str,
        business_registration_number: str, period_years: int,
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
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            reference = connection.execute(
                _COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchone()
            if reference is None:
                raise LookupError(f"bid notice '{reference_bid_notice_id}' was not found")
            reference = dict(reference)
            rows = connection.execute(
                _COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY,
                {
                    "notice_number": notice_number,
                    "notice_order": notice_order,
                    "company_number": business_registration_number,
                    "period_years": period_years,
                },
            ).fetchall()
        return reference, [dict(row) for row in rows]

    def count_many(
        self, catalog: RegistryCatalog, *, reference_bid_notice_id: str,
        business_registration_numbers: list[str], period_years: int,
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
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _COMPANY_SIMILAR_PROJECT_METRICS_QUERY,
                {
                    "notice_number": notice_number,
                    "notice_order": notice_order,
                    "company_numbers": business_registration_numbers,
                    "period_years": period_years,
                },
            ).fetchall()
        return {
            str(row["company_number"]): {
                key: int(row[key]) for key in (
                    "candidate_count", "event_count", "strong_event_count",
                    "limited_event_count", "reference_only_event_count",
                    "similar_amount_event_count",
                )
            }
            for row in rows
        }


class ProcurementProfileReader:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def activities(
        self, catalog: RegistryCatalog, *, organization_code: str | None,
        company_numbers: list[str], period_from: date, period_to: date,
    ) -> list[dict[str, Any]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = [dict(row) for row in connection.execute(
                _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
                {
                    "organization_code": organization_code,
                    "company_numbers": company_numbers,
                    "period_from": period_from,
                    "period_to": period_to,
                },
            ).fetchall()]
            missing_codes = sorted({
                str(row["procurement_classification_number"])
                for row in rows
                if row.get("procurement_classification_number")
                and not row.get("procurement_large_classification_name")
                and not row.get("procurement_middle_classification_name")
            })
            if missing_codes:
                hierarchy = {
                    str(row["procurement_classification_number"]): dict(row)
                    for row in connection.execute(
                        _PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY,
                        {"classification_numbers": missing_codes},
                    ).fetchall()
                }
                for row in rows:
                    item = hierarchy.get(str(row.get("procurement_classification_number") or ""))
                    if not item:
                        continue
                    for key in (
                        "procurement_large_classification_name",
                        "procurement_middle_classification_name", "purchase_items",
                    ):
                        if not row.get(key):
                            row[key] = item.get(key)
            notice_fields = {
                str(row["bid_notice_id"]): row for row in rows
                if row.get("procurement_classification_number")
            }
            for row in rows:
                if row.get("procurement_classification_number"):
                    continue
                field = notice_fields.get(str(row["bid_notice_id"]))
                if not field:
                    continue
                for key in (
                    "procurement_classification_number",
                    "procurement_classification_name",
                    "procurement_large_classification_name",
                    "procurement_middle_classification_name", "purchase_items",
                ):
                    row[key] = field.get(key)
            return rows

    def organization_award_history(
        self, catalog: RegistryCatalog, *, organization_code: str, history_from: date,
    ) -> tuple[dict[str, date], date | None]:
        """Return each company's first observed contract in the fixed history window."""
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                _ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY,
                {"organization_code": organization_code, "history_from": history_from},
            ).fetchall()
        first_dates = {
            str(row["company_number"]): row["first_activity_date"]
            for row in rows if row.get("company_number") and row.get("first_activity_date")
        }
        return first_dates, history_from

    def bid_context(
        self, catalog: RegistryCatalog, *, bid_notice_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = catalog.sources["teoria_public_procurement"].source
        database_url = self.environment.get(source.access.connection_env)
        if not database_url:
            raise RuntimeError(
                f"missing database credential environment variable: {source.access.connection_env}"
            )
        notice_number, separator, notice_order = bid_notice_id.rpartition(":")
        if not separator:
            raise ValueError(f"invalid bid notice id '{bid_notice_id}'")
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            notice = connection.execute(
                _BID_RELATIONSHIP_NOTICE_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchone()
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            participants = connection.execute(
                _BID_RELATIONSHIP_PARTICIPANTS_QUERY,
                {"notice_number": notice_number, "notice_order": notice_order},
            ).fetchall()
        return dict(notice), [dict(row) for row in participants]


async def execute_similar_bid_notices(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: SimilarBidNoticeReader | None = None,
) -> CapabilityResult:
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 5))
    result_statuses = list(dict.fromkeys(map(str, inputs.get(
        "result_statuses", ["awarded", "contracted"],
    ))))
    invalid_statuses = set(result_statuses) - {"awarded", "contracted"}
    if not result_statuses or invalid_statuses:
        raise CapabilityExecutionError(
            "invalid_result_statuses",
            "result_statuses must contain awarded and/or contracted",
            capability_id=capability_id,
        )
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    resolved_reader = reader or SimilarBidNoticeReader()
    try:
        notice, rows = await asyncio.to_thread(
            resolved_reader.find, catalog, bid_notice_id,
            period_years=period_years, result_statuses=result_statuses,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    scored = [_similar_notice_item(notice, row) for row in rows]
    scored = [item for item in scored if item["relationship_type"] is not None]
    scored.sort(key=lambda item: item.get("award_date") or date.min, reverse=True)
    scored.sort(key=lambda item: item["comparison_score"], reverse=True)
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in scored:
        key = (
            str(item.get("organization_code") or ""),
            _normalized_title(str(item.get("notice_name") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    total_items = len(deduplicated)
    start = (page - 1) * page_size
    items = deduplicated[start:start + page_size]
    comparable_notices = [item for item in items if item["relationship_type"] == "comparable"]
    organization_field_notices = [
        item for item in items if item["relationship_type"] == "same_organization_field"
    ]
    title_search_results = [
        item for item in items if item["relationship_type"] == "title_search_result"
    ]
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.find_similar_bid_notices",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    objects = []
    for item in items:
        properties = {
            "similar_bid_notice_id": f"{bid_notice_id}:{item['bid_notice_id']}",
            "source_bid_notice_id": bid_notice_id,
            "bid_notice_id": item["bid_notice_id"],
            "notice_name": item["notice_name"],
            "notice_published_date": item["notice_published_date"],
            "award_date": item["award_date"],
            "similarity_score": item["similarity_score"],
            "similarity_level": item["similarity_level"],
            "similarity_profile": SIMILARITY_PROFILE,
            "relationship_type": item["relationship_type"],
            "comparison_score": item["comparison_score"],
            "comparison_quality": item["comparison_quality"],
            "comparison_eligible": item["comparison_eligible"],
            "price_reference_eligible": item["price_reference_eligible"],
            "matched_factors": item["matched_factors"],
            "different_factors": item["different_factors"],
        }
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="similar_bid_notice",
            object_id=properties["similar_bid_notice_id"], properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    return CapabilityResult(
        capability_id=capability_id, objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "items": items,
            "comparable_notices": comparable_notices,
            "organization_field_notices": organization_field_notices,
            "title_search_results": title_search_results,
            "pagination": {
                "page": page, "page_size": page_size, "total_items": total_items,
            },
            "policy": {
                "similarity_profile": SIMILARITY_PROFILE,
                "period_years": period_years,
                "result_statuses": result_statuses,
                "candidate_pool_limit": SIMILARITY_CANDIDATE_LIMIT,
            },
        },
    )


async def execute_bid_relevant_companies(
    runner: Any,
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: BidCompetitorCandidateReader | None = None,
) -> CapabilityResult:
    resolved_reader = reader or BidCompetitorCandidateReader()
    bid_notice_id = str(inputs["bid_notice_id"])
    similar_bid_notice_ids = list(dict.fromkeys(map(str, inputs["similar_bid_notice_ids"])))
    limit = int(inputs.get("limit", 20))
    if not similar_bid_notice_ids or len(similar_bid_notice_ids) > 100:
        raise CapabilityExecutionError(
            "invalid_similar_bid_notice_ids",
            "similar_bid_notice_ids must contain between 1 and 100 unique ids",
            capability_id=capability_id,
        )
    try:
        notice, rows, required_regions, industry_requirements = await asyncio.to_thread(
            resolved_reader.find_relevant,
            catalog,
            bid_notice_id,
            similar_bid_notice_ids,
            limit=limit,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except ValueError as exc:
        code = "invalid_similar_bid_notice_id" if "invalid bid notice id" in str(exc) else "demand_organization_unavailable"
        raise CapabilityExecutionError(code, str(exc), capability_id=capability_id) from exc
    except (psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    company_evidence = await _load_company_evidence(runner, catalog, rows)
    as_of = notice["as_of"]
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    deadline = notice.get("bid_deadline_at")
    eligibility_reference_date = deadline.date() if isinstance(deadline, datetime) else as_of_date
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution",
        source="teoria_runtime",
        operation=RELEVANCE_PROCESSOR_ID,
        mapping="public_procurement_market_context",
        observed_at=observed_at,
        record_keys=[bid_notice_id, *similar_bid_notice_ids],
    )
    items = [
        _relevant_company_item(
            dict(row), notice, required_regions, industry_requirements,
            company_evidence.get(str(row["company_number"])), as_of_date,
            eligibility_reference_date, catalog,
        )
        for row in rows
    ]
    objects = []
    for item in items:
        properties = {
            "relevant_company_id": f"{bid_notice_id}:{item['company_number']}",
            "bid_notice_id": bid_notice_id,
            "company_number": item["company_number"],
            "company_name": item["company_name"],
            "similar_participation_count": item["similar_history"]["participation_count"],
            "similar_award_count": item["similar_history"]["award_count"],
            "similar_contract_count": item["similar_history"]["contract_count"],
            "similar_unified_contract_count": item["similar_history"]["unified_contract_count"],
            "organization_participation_count": item["organization_relationship"]["participation_count"],
            "organization_award_count": item["organization_relationship"]["award_count"],
            "organization_contract_count": item["organization_relationship"]["contract_count"],
            "organization_unified_contract_count": item["organization_relationship"]["unified_contract_count"],
            "organization_contract_amount": item["organization_relationship"]["contract_amount"],
            "first_activity_date": item["organization_relationship"]["first_activity_date"],
            "latest_activity_date": item["organization_relationship"]["latest_activity_date"],
            "region_status": item["region_eligibility"]["status"],
            "industry_license_status": item["industry_license_eligibility"]["status"],
            "relevance_profile": RELEVANCE_PROFILE,
            "ranking_profile": RELEVANCE_RANKING_PROFILE,
        }
        objects.append(MaterializedObject(
            ontology="public_procurement",
            object_type="bid_relevant_company",
            object_id=properties["relevant_company_id"],
            properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    return CapabilityResult(
        capability_id=capability_id,
        objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "similar_bid_notice_ids": similar_bid_notice_ids,
            "organization": {
                "role": "demand_organization",
                "code": notice["demand_organization_code"],
                "name": notice["demand_organization_name"],
            },
            "required_regions": required_regions,
            "policy": {
                "relevance_profile": RELEVANCE_PROFILE,
                "ranking_profile": RELEVANCE_RANKING_PROFILE,
                "signal_policy_version": SIGNAL_POLICY_VERSION,
            },
            "items": items,
        },
    )


async def execute_organization_field_companies(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    similar_reader: SimilarBidNoticeReader | None = None,
    company_reader: BidCompetitorCandidateReader | None = None,
    event_reader: OrganizationFieldEventReader | None = None,
    similar_experience_reader: CompanySimilarProjectExperienceReader | None = None,
) -> CapabilityResult:
    total_started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 5))
    limit = int(inputs.get("limit", 50))
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_key = (bid_notice_id, period_years, limit, registry_version)
    cached = _ORGANIZATION_FIELD_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ORGANIZATION_FIELD_CACHE_TTL_SECONDS:
        result = cached[1].model_copy(deep=True)
        result.outcome["timings"] = {
            "current_notice_lookup_ms": 0.0,
            "organization_history_query_ms": 0.0,
            "market_similar_query_ms": 0.0,
            "contract_attribution_ms": 0.0,
            "company_aggregation_ms": 0.0,
            "total_ms": round((time.perf_counter() - total_started) * 1000, 3),
            "cache_hit": True,
        }
        return result
    if cached:
        _ORGANIZATION_FIELD_CACHE.pop(cache_key, None)
    timings: dict[str, float] = {}
    try:
        resolved_similar_reader = similar_reader or SimilarBidNoticeReader()
        similar_kwargs: dict[str, Any] = {
            "period_years": period_years,
            "result_statuses": ["awarded", "contracted"],
        }
        if similar_reader is None:
            similar_kwargs["timings"] = timings
            similar_kwargs["candidate_limit"] = max(100, limit * 2)
            similar_kwargs["similarity_threshold"] = 0.15
        notice, candidate_rows = await asyncio.to_thread(
            resolved_similar_reader.find, catalog, bid_notice_id, **similar_kwargs,
        )
        candidates = [_similar_notice_item(notice, row) for row in candidate_rows]
        candidates = [item for item in candidates if item["relationship_type"] is not None]
        candidate_by_id = {str(item["bid_notice_id"]): item for item in candidates}
        organization_field_ids = {
            notice_id for notice_id, item in candidate_by_id.items()
            if item["matched_features"]["same_organization"]
            and item["matched_features"]["field_score"] > 0
        }
        market_similar_ids = {
            notice_id for notice_id, item in candidate_by_id.items()
            if not item["matched_features"]["same_organization"]
            and item["comparison_eligible"]
        }
        selected_ids = list(dict.fromkeys([
            *sorted(organization_field_ids), *sorted(market_similar_ids),
        ]))[:100]
        if not selected_ids:
            selected_ids = [bid_notice_id]
        resolved_company_reader = company_reader or BidCompetitorCandidateReader()
        company_kwargs: dict[str, Any] = {"limit": max(limit * 6, 200)}
        if company_reader is None:
            company_kwargs["timings"] = timings
            company_kwargs["award_contract_only"] = True
        relationship_notice, rows, _, _ = await asyncio.to_thread(
            resolved_company_reader.find_relevant,
            catalog, bid_notice_id, selected_ids, **company_kwargs,
        )
        event_rows: list[dict[str, Any]] = []
        if event_reader is not None or (similar_reader is None and company_reader is None):
            resolved_event_reader = event_reader or OrganizationFieldEventReader()
            event_started = time.perf_counter()
            event_rows = await asyncio.to_thread(
                resolved_event_reader.find, catalog,
                organization_code=str(notice["demand_organization_code"]),
                work_type=str(notice["work_type"]), as_of=notice["as_of"],
            )
            timings["organization_field_event_query_ms"] = (
                time.perf_counter() - event_started
            ) * 1000
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    aggregation_started = time.perf_counter()
    groups: dict[str, list[dict[str, Any]]] = {
        "organization_field_companies": [],
        "market_similar_companies": [],
        "organization_other_companies": [],
    }
    event_analysis = _organization_field_event_analysis(event_rows, notice, period_years)
    organization_metrics = _organization_relationship_metrics(
        event_analysis["all_events"], notice.get("as_of"), period_years,
    )
    for row in rows:
        won_activities = [
            activity for activity in row.get("similar_activities") or []
            if activity.get("result") in {"awarded", "contracted"}
        ]
        won_notice_ids = {str(activity["bid_notice_id"]) for activity in won_activities}
        organization_field_wins = won_notice_ids & organization_field_ids
        market_wins = won_notice_ids & market_similar_ids
        target_fields = _business_fields(str(notice.get("notice_name") or ""))
        if "1468" in set(map(str, notice.get("industry_codes") or [])) \
                and "시스템" in str(notice.get("notice_name") or ""):
            target_fields.add("information_system")
        target_projects = _project_types(str(notice.get("notice_name") or ""))
        target_amount = notice.get("estimated_price") or notice.get("allocated_budget")
        organization_won_activities = [
            activity for activity in row.get("organization_activities") or []
            if activity.get("result") in {"awarded", "contracted"}
        ]
        direct_organization_field_activities = [
            activity for activity in organization_won_activities
            if target_fields & _business_fields(str(activity.get("notice_name") or ""))
        ]
        has_organization_award = bool(
            row.get("organization_award_count") or row.get("organization_contract_count")
        )
        if organization_field_wins or direct_organization_field_activities:
            group_key, relationship_group = "organization_field_companies", "organization_field"
            relevant_ids = organization_field_wins | {
                str(activity["bid_notice_id"])
                for activity in direct_organization_field_activities
            }
        elif market_wins:
            group_key, relationship_group = "market_similar_companies", "market_similar"
            relevant_ids = market_wins
        elif has_organization_award:
            group_key, relationship_group = "organization_other_companies", "organization_other"
            relevant_ids = set()
        else:
            continue
        related_items = [candidate_by_id[item] for item in relevant_ids if item in candidate_by_id]
        same_field_awards = {
            (activity["bid_notice_id"], activity.get("bid_classification_number"),
             activity.get("rebid_number"))
            for activity in won_activities
            if activity.get("result") == "awarded"
            and str(activity["bid_notice_id"]) in relevant_ids
        }
        same_field_awards.update({
            (activity["bid_notice_id"], activity.get("bid_classification_number"),
             activity.get("rebid_number"))
            for activity in direct_organization_field_activities
            if activity.get("result") == "awarded"
        })
        same_field_contracts = {
            str(activity.get("unified_contract_number"))
            for activity in won_activities
            if activity.get("result") == "contracted"
            and str(activity["bid_notice_id"]) in relevant_ids
            and activity.get("unified_contract_number")
        }
        same_field_contracts.update({
            str(activity["unified_contract_number"])
            for activity in direct_organization_field_activities
            if activity.get("result") == "contracted"
            and activity.get("unified_contract_number")
        })
        same_project_notice_ids = {
            str(item["bid_notice_id"]) for item in related_items
            if any(str(factor).startswith("same_project_type_") for factor in item["matched_factors"])
        } | {
            str(activity["bid_notice_id"]) for activity in direct_organization_field_activities
            if target_projects & _project_types(str(activity.get("notice_name") or ""))
        }
        same_project_type_count = len(same_project_notice_ids)
        similar_amount_notice_ids = {
            str(item["bid_notice_id"]) for item in related_items
            if "similar_amount_range" in item["matched_factors"]
        } | {
            str(activity["bid_notice_id"]) for activity in direct_organization_field_activities
            if _amount_similarity(target_amount, activity.get("bid_amount"))[0] >= 0.5
        }
        similar_amount_count = len(similar_amount_notice_ids)
        factors = {factor for item in related_items for factor in item["matched_factors"]}
        for activity in direct_organization_field_activities:
            factors.update(target_fields & _business_fields(str(activity.get("notice_name") or "")))
            factors.update(
                f"same_project_type_{kind}"
                for kind in target_projects & _project_types(str(activity.get("notice_name") or ""))
            )
        if has_organization_award:
            factors.add("same_organization")
        if int(row.get("organization_award_count") or 0) >= 2:
            factors.add("repeat_organization_award")
        item = {
            "company_number": str(row["company_number"]),
            "company_name": row.get("company_name"),
            "relationship_group": relationship_group,
            "same_organization_award_count": int(row.get("organization_award_count") or 0),
            "same_organization_contract_count": int(row.get("organization_contract_count") or 0),
            "same_organization_contract_amount": _number(row.get("organization_contract_amount")),
            "same_organization_contract_amount_complete": bool(row.get("contract_amount_complete")),
            "same_field_award_count": len(same_field_awards),
            "same_field_contract_count": len(same_field_contracts),
            "same_project_type_count": same_project_type_count,
            "similar_amount_count": similar_amount_count,
            "latest_activity_date": row.get("organization_latest_activity_date")
                or row.get("similar_latest_activity_date"),
            "matched_factors": sorted(factors),
            "sample_notice_ids": sorted(relevant_ids)[:10],
        }
        groups[group_key].append(item)

    items_by_company = {
        item["company_number"]: item
        for values in groups.values() for item in values
    }
    for company_number, metrics in event_analysis["company_metrics"].items():
        item = items_by_company.get(company_number)
        if item is None and metrics["same_field_event_count"]:
            event = next(
                candidate for candidate in event_analysis["events"]
                if company_number in candidate["members"]
            )
            member = event["members"][company_number]
            item = {
                "company_number": company_number,
                "company_name": member.get("company_name"),
                "relationship_group": "organization_field",
                "same_organization_award_count": metrics["same_field_event_count"],
                "same_organization_contract_count": 0,
                "same_organization_contract_amount": metrics["same_field_contract_amount"],
                "same_organization_contract_amount_complete": metrics[
                    "same_field_contract_amount_complete"
                ],
                "same_field_award_count": metrics["same_field_event_count"],
                "same_field_contract_count": 0,
                "same_project_type_count": metrics["same_project_type_event_count"],
                "similar_amount_count": metrics["similar_amount_event_count"],
                "latest_activity_date": metrics["latest_award_date"],
                "matched_factors": ["same_organization", "information_system"],
                "sample_notice_ids": [
                    value["notice_id"] for value in metrics["representative_notices"]
                    if value.get("notice_id")
                ],
            }
            groups["organization_field_companies"].append(item)
            items_by_company[company_number] = item
        if item is not None:
            item.update(metrics)

    legacy_relationship_candidates = []
    current_field_companies = []
    for item in groups["organization_field_companies"]:
        if int(item.get("same_field_event_count") or 0) >= 1:
            current_field_companies.append(item)
        else:
            legacy_relationship_candidates.append(item)
    groups["organization_field_companies"] = current_field_companies

    def ranking(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            item["same_field_award_count"] + item["same_field_contract_count"],
            item["same_project_type_count"], item["similar_amount_count"],
            item["same_organization_award_count"] + item["same_organization_contract_count"],
            item["latest_activity_date"] or date.min,
        )

    for group_key, values in groups.items():
        values.sort(key=ranking, reverse=True)
        if group_key != "organization_field_companies":
            del values[limit:]
    all_items = [
        *groups["organization_field_companies"],
        *groups["market_similar_companies"],
        *groups["organization_other_companies"],
    ]
    company_numbers = sorted({item["company_number"] for item in all_items})
    experience_metrics: dict[str, dict[str, int]] = {}
    if company_numbers and (
        similar_experience_reader is not None
        or (similar_reader is None and company_reader is None)
    ):
        resolved_experience_reader = (
            similar_experience_reader or CompanySimilarProjectExperienceReader()
        )
        experience_started = time.perf_counter()
        try:
            experience_metrics = await asyncio.to_thread(
                resolved_experience_reader.count_many,
                catalog,
                reference_bid_notice_id=bid_notice_id,
                business_registration_numbers=company_numbers,
                period_years=period_years,
            )
        except (ValueError, psycopg.Error, RuntimeError) as exc:
            raise CapabilityExecutionError(
                "database_source_error", str(exc), capability_id=capability_id,
                source_id="teoria_public_procurement",
                retryable=isinstance(exc, psycopg.Error),
            ) from exc
        timings["similar_project_experience_query_ms"] = (
            time.perf_counter() - experience_started
        ) * 1000
    for item in all_items:
        company_number = item["company_number"]
        metrics = organization_metrics.get(company_number, {})
        annual_activity = metrics.get("annual_activity", [])
        annual_completeness = [
            value["amount_completeness"] for value in annual_activity
        ]
        amount_completeness = (
            "complete" if annual_completeness and all(
                status == "complete" for status in annual_completeness
            )
            else "unknown" if not annual_completeness or all(
                status == "unknown" for status in annual_completeness
            )
            else "partial"
        )
        item["organization_relationship"] = {
            "award_event_count": int(metrics.get("same_field_event_count") or 0),
            "yearly_activity": annual_activity,
            "total_attributed_contract_amount": sum(
                value["attributed_contract_amount"] for value in annual_activity
            ),
            "amount_completeness": amount_completeness,
        }
        similar_metrics = experience_metrics.get(company_number, {})
        item["similar_project_experience"] = {
            "candidate_count": int(similar_metrics.get("candidate_count") or 0),
            "event_count": int(similar_metrics.get("event_count") or 0),
            "strong_event_count": int(similar_metrics.get("strong_event_count") or 0),
            "limited_event_count": int(similar_metrics.get("limited_event_count") or 0),
            "reference_only_event_count": int(
                similar_metrics.get("reference_only_event_count") or 0
            ),
            "similar_amount_event_count": int(
                similar_metrics.get("similar_amount_event_count") or 0
            ),
        }
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.analyze_bid_organization_field_companies",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    objects = []
    for item in all_items:
        properties = {
            "organization_field_company_id": f"{bid_notice_id}:{item['company_number']}",
            "bid_notice_id": bid_notice_id,
            **item,
        }
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="bid_organization_field_company",
            object_id=properties["organization_field_company_id"], properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    timings["company_aggregation_ms"] = (time.perf_counter() - aggregation_started) * 1000
    timings.setdefault("current_notice_lookup_ms", 0.0)
    timings.setdefault("organization_history_query_ms", 0.0)
    timings.setdefault("market_similar_query_ms", 0.0)
    timings.setdefault("organization_field_event_query_ms", 0.0)
    timings["contract_attribution_ms"] = 0.0
    timings["total_ms"] = (time.perf_counter() - total_started) * 1000
    timings = {key: round(value, 3) for key, value in timings.items()}
    timings["cache_hit"] = False
    result = CapabilityResult(
        capability_id=capability_id, objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "analysis_basis": {
                **_organization_field_analysis_basis(notice, period_years),
                "organization_code": notice.get("demand_organization_code"),
                "observation_started_at": event_analysis["market_entry"]["observation_started_at"],
            },
            "organization": {
                "code": relationship_notice["demand_organization_code"],
                "name": relationship_notice["demand_organization_name"],
            },
            **groups,
            "legacy_relationship_candidates": legacy_relationship_candidates,
            "event_deduplication": event_analysis["event_deduplication"],
            "market_structure": event_analysis["market_structure"],
            "market_entry": event_analysis["market_entry"],
            "data_completeness": event_analysis["data_completeness"],
            "policy": {
                "profile": "organization_field_company_evidence_v1",
                "period_years": period_years,
                "relationship_evidence": ["awarded", "contracted"],
                "participation_is_relationship_evidence": False,
                "cache_ttl_seconds": ORGANIZATION_FIELD_CACHE_TTL_SECONDS,
                "contract_attribution_timing": "included_in_organization_history_query_ms",
            },
            "timings": timings,
        },
    )
    if len(_ORGANIZATION_FIELD_CACHE) >= 128:
        oldest_key = min(_ORGANIZATION_FIELD_CACHE, key=lambda key: _ORGANIZATION_FIELD_CACHE[key][0])
        _ORGANIZATION_FIELD_CACHE.pop(oldest_key, None)
    _ORGANIZATION_FIELD_CACHE[cache_key] = (time.monotonic(), result.model_copy(deep=True))
    return result


async def execute_bid_project_lineage(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: SimilarBidNoticeReader | None = None,
) -> CapabilityResult:
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 10))
    try:
        resolved_reader = reader or SimilarBidNoticeReader()
        kwargs: dict[str, Any] = {
            "period_years": period_years,
            "result_statuses": ["awarded", "contracted"],
        }
        if reader is None:
            kwargs.update(candidate_limit=200, similarity_threshold=0.10)
        notice, rows = await asyncio.to_thread(
            resolved_reader.find, catalog, bid_notice_id, **kwargs,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    current_title = str(notice.get("notice_name") or "")
    current_published = notice.get("notice_published_date")
    current_projects = _project_types(current_title)
    current_fields = _business_fields(current_title)
    if "1468" in set(map(str, notice.get("industry_codes") or [])) and "시스템" in current_title:
        current_fields.add("information_system")
    items = []
    for row in rows:
        if current_published and row.get("notice_published_date") \
                and row["notice_published_date"] >= current_published:
            continue
        previous_title = str(row.get("notice_name") or "")
        previous_projects = _project_types(previous_title)
        previous_fields = _business_fields(previous_title)
        if "1468" in set(map(str, row.get("industry_codes") or [])) and "시스템" in previous_title:
            previous_fields.add("information_system")
        same_organization = bool(
            notice.get("demand_organization_code")
            and notice.get("demand_organization_code") == row.get("demand_organization_code")
        )
        field_overlap = sorted(current_fields & previous_fields)
        candidate_type = None
        if "build" in previous_projects and "improvement" in current_projects:
            candidate_type = "build_to_improvement"
        elif "build" in previous_projects and "maintenance" in current_projects:
            candidate_type = "build_to_maintenance"
        elif "차세대" in _compact(current_title) and field_overlap:
            candidate_type = "existing_to_next_generation"
        elif re.search(r"\b[1-9]\s*단계|\([1-9]차\)", current_title) and field_overlap:
            candidate_type = "phased_successor"
        elif same_organization and field_overlap:
            candidate_type = "same_asset_or_field_candidate"
        if candidate_type is None:
            continue
        reasons = []
        if same_organization:
            reasons.append("same_demand_organization")
        reasons.extend(f"same_field_{value}" for value in field_overlap)
        if previous_projects:
            reasons.append("predecessor_project_type_" + "_".join(sorted(previous_projects)))
        if current_projects:
            reasons.append("successor_project_type_" + "_".join(sorted(current_projects)))
        title_score = _jaccard(_title_tokens(current_title), _title_tokens(previous_title))
        confidence = min(0.65, round(
            0.20 + 0.20 * float(same_organization)
            + 0.15 * float(bool(field_overlap)) + 0.10 * title_score,
            4,
        ))
        items.append({
            "relationship_type": "related_candidate",
            "candidate_relationship_type": candidate_type,
            "predecessor_bid_notice_id": row.get("bid_notice_id"),
            "successor_bid_notice_id": bid_notice_id,
            "project_stage": {
                "predecessor": sorted(previous_projects),
                "successor": sorted(current_projects),
            },
            "performing_company_number": row.get("winner_business_registration_number"),
            "performing_company_name": row.get("winner_name"),
            "contract_amount": _number(row.get("winning_amount")),
            "performance_period": None,
            "confidence": confidence,
            "reason_codes": reasons,
            "evidence_labels": [],
            "evidence": [{
                "source_type": "structured_notice_metadata",
                "bid_notice_id": row.get("bid_notice_id"),
                "original_text": previous_title,
            }],
            "confirmation_status": "requires_source_evidence",
        })
    items.sort(key=lambda item: item["confidence"], reverse=True)
    limit = int(inputs.get("limit", 20))
    items = items[:limit]
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.find_bid_project_lineage",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    objects = []
    for item in items:
        object_id = (
            f"{item['predecessor_bid_notice_id']}:{item['successor_bid_notice_id']}"
        )
        properties = {"project_lineage_id": object_id, **item}
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="bid_project_lineage",
            object_id=object_id, properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    confirmed_items = [
        item for item in items if item["relationship_type"] in {"confirmed", "probable"}
    ]
    related_candidates = [
        item for item in items if item["relationship_type"] == "related_candidate"
    ]
    return CapabilityResult(
        capability_id=capability_id, objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "items": items,
            "confirmed_items": confirmed_items,
            "related_candidates": related_candidates,
            "confirmed_count": len(confirmed_items),
            "candidate_count": len(related_candidates),
            "policy": {
                "profile": "bid_project_lineage_v1",
                "weak_evidence_relationship": "related_candidate",
                "title_similarity_alone_confirms_lineage": False,
            },
        },
    )


async def execute_organization_company_field_relationship(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: OrganizationFieldEventReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    organization_code = str(inputs["organization_code"])
    company_number = "".join(
        character for character in str(inputs["business_registration_number"])
        if character.isdigit()
    )
    field_code = str(inputs["field_code"]) if inputs.get("field_code") else None
    supported_fields = {
        "information_system": ("정보시스템", "정보시스템 소프트웨어 전산"),
        "security": ("정보보호·보안", "정보보호 보안 방화벽"),
        "communication": ("정보통신·네트워크", "정보통신 통신망 네트워크"),
    }
    if field_code and field_code not in supported_fields:
        raise CapabilityExecutionError(
            "unsupported_field_code", f"unsupported field_code '{field_code}'",
            capability_id=capability_id,
        )
    period_years = int(inputs.get("period_years", 10))
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    reference_bid_notice_id = (
        str(inputs["reference_bid_notice_id"])
        if inputs.get("reference_bid_notice_id") else None
    )
    work_type = str(inputs["work_type"]) if inputs.get("work_type") else None
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_key = (
        organization_code, company_number, field_code, period_years, page, page_size,
        reference_bid_notice_id, work_type, registry_version,
    )
    cached = _ORGANIZATION_COMPANY_FIELD_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < ORGANIZATION_FIELD_CACHE_TTL_SECONDS:
        result = cached[1].model_copy(deep=True)
        result.outcome["timings"] = {
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
            "cache_hit": True,
        }
        return result

    resolved_reader = reader or OrganizationFieldEventReader()
    try:
        context = await asyncio.to_thread(
            resolved_reader.context, catalog, organization_code=organization_code,
            business_registration_number=company_number,
            reference_bid_notice_id=reference_bid_notice_id,
        )
        reference = context["reference_notice"]
        as_of = reference.get("as_of") if reference else datetime.combine(
            date.today() + timedelta(days=1), datetime.min.time(), timezone.utc
        )
        rows = await asyncio.to_thread(
            resolved_reader.find, catalog, organization_code=organization_code,
            work_type=work_type, as_of=as_of,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    if reference:
        analysis_notice = dict(reference)
    else:
        label, synthetic_title = supported_fields.get(field_code, (None, ""))
        analysis_notice = {
            "notice_name": synthetic_title,
            "estimated_price": None, "allocated_budget": None,
            "industry_codes": [], "as_of": as_of,
        }
        if field_code is None:
            analysis_notice["include_all_fields"] = True
    analysis = _organization_field_event_analysis(rows, analysis_notice, period_years)
    events = [
        event for event in analysis["events"] if company_number in event["members"]
    ]
    events.sort(key=lambda event: event.get("awarded_at") or date.min, reverse=True)
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    period_start = _fiscal_period_start(as_of_date, period_years)
    contract_event_count = 0
    contract_version_count = 0
    for event in events:
        member_dates = [
            value for value in event["members"][company_number].get(
                "contract_activity_dates"
            ) or []
            if period_start <= value < as_of_date
        ]
        if member_dates:
            contract_event_count += 1
            contract_version_count += len(member_dates)

    project_counts: dict[str, int] = {}
    amount_counts = {"under_1b": 0, "1b_to_3b": 0, "3b_to_10b": 0, "over_10b": 0}
    yearly: dict[int, dict[str, Any]] = {}
    event_items = []
    attributed_event_total = Decimal("0")
    target_amount = analysis_notice.get("estimated_price") or analysis_notice.get("allocated_budget")
    for event in events:
        member = event["members"][company_number]
        members = list(event["members"].values())
        shares = [value.get("share_rate") for value in members]
        share_total = sum(
            (Decimal(str(value)) for value in shares if value is not None), Decimal("0")
        )
        if members and all(value is not None for value in shares) and share_total:
            credit = Decimal(str(member["share_rate"])) / share_total
            share_percent = _number(Decimal(str(member["share_rate"])))
            share_source = "confirmed"
        else:
            credit = Decimal("1") / Decimal(str(len(members)))
            share_percent = _number(credit * Decimal("100"))
            share_source = "equal_split"
        attributed_event_total += credit
        project_type = _primary_project_type(str(event.get("notice_name") or ""))
        project_counts[project_type] = project_counts.get(project_type, 0) + 1
        amount = event.get("contract_amount") or event.get("award_amount")
        amount_number = Decimal(str(amount)) if amount is not None else None
        bucket = (
            "under_1b" if amount_number is not None and amount_number < Decimal("1000000000") else
            "1b_to_3b" if amount_number is not None and amount_number < Decimal("3000000000") else
            "3b_to_10b" if amount_number is not None and amount_number < Decimal("10000000000") else
            "over_10b"
        )
        amount_counts[bucket] += 1
        year = event["awarded_at"].year
        yearly_item = yearly.setdefault(year, {
            "year": year, "event_count": 0,
            "attributed_event_count": Decimal("0"),
            "total_attributed_amount": Decimal("0"),
        })
        yearly_item["event_count"] += 1
        yearly_item["attributed_event_count"] += credit
        if member.get("attributed_amount") is not None:
            yearly_item["total_attributed_amount"] += Decimal(str(member["attributed_amount"]))
        is_similar = None if target_amount is None else (
            _amount_similarity(target_amount, amount)[0] >= 0.5
        )
        event_items.append({
            "award_event_id": event["event_id"],
            "bid_notice_id": event.get("notice_id"),
            "notice_name": event.get("notice_name"),
            "notice_published_date": event.get("notice_published_date"),
            "award_date": event.get("award_date"),
            "contract_date": event.get("contract_date"),
            "project_type": project_type,
            "project_type_label": _project_type_label(project_type),
            "award_amount": event.get("award_amount"),
            "contract_amount": event.get("contract_amount"),
            "attributed_contract_amount": member.get("attributed_amount"),
            "attributed_contract_amount_completeness": (
                "complete" if member.get("attributed_amount") is not None
                else "partial" if "contract" in event["source_kinds"]
                else "unknown"
            ),
            "joint_contract": len(members) > 1,
            "company_role": (
                "sole" if len(members) == 1
                else "consortium_lead" if member.get("supplier_role_name") in {
                    "대표사", "주계약자", "대표업체",
                }
                else "consortium_member"
            ),
            "share_percent": share_percent,
            "share_source": share_source,
            "field_match_reasons": [field_code] if field_code else [],
            "is_similar_amount": is_similar,
            "similar_amount_reason": (
                None if target_amount is not None else "reference_amount_not_provided"
            ),
        })

    total_items = len(event_items)
    offset = (page - 1) * page_size
    paged_events = event_items[offset:offset + page_size]
    metrics = analysis["company_metrics"].get(company_number, {})
    annual_activity = metrics.get("annual_activity", [])
    annual_completeness = [item["amount_completeness"] for item in annual_activity]
    relationship_amount_completeness = (
        "complete" if annual_completeness and all(
            status == "complete" for status in annual_completeness
        )
        else "unknown" if not annual_completeness or all(
            status == "unknown" for status in annual_completeness
        )
        else "partial"
    )
    total_attributed_contract_amount = sum(
        item["attributed_contract_amount"] for item in annual_activity
    )
    project_order = ["build", "improvement", "maintenance", "consulting", "unknown"]
    project_distribution = [{
        "project_type": kind, "label": _project_type_label(kind),
        "event_count": project_counts.get(kind, 0),
    } for kind in project_order]
    amount_labels = {
        "under_1b": "10억원 미만", "1b_to_3b": "10~30억원",
        "3b_to_10b": "30~100억원", "over_10b": "100억원 이상",
    }
    amount_distribution = [{
        "range": key, "label": amount_labels[key], "event_count": amount_counts[key],
    } for key in amount_labels]
    yearly_activity = [{
        **item,
        "attributed_event_count": _number(item["attributed_event_count"]),
        "total_attributed_amount": _number(item["total_attributed_amount"]),
    } for _, item in sorted(yearly.items(), reverse=True)]
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.get_organization_company_field_relationship",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[organization_code, company_number],
    )
    properties = {
        "organization_company_field_relationship_id": (
            f"{organization_code}:{company_number}:{field_code or 'all'}"
        ),
        "organization_code": organization_code,
        "company_number": company_number,
        "field_code": field_code,
        "award_event_count": total_items,
    }
    result = CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement",
            object_type="organization_company_field_relationship",
            object_id=properties["organization_company_field_relationship_id"],
            properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )],
        outcome={
            "organization": {
                "code": organization_code,
                "name": context["organization"].get("organization_name"),
            },
            "company": {
                "business_registration_number": company_number,
                "name": context["company"].get("company_name"),
            },
            "field": {
                "code": field_code,
                "label": supported_fields.get(field_code, (None, ""))[0],
            },
            "analysis_basis": {
                "period_years": period_years,
                "period_from": period_start,
                "period_to": as_of_date - timedelta(days=1),
                "period_type": "calendar_fiscal_years",
                "work_type": work_type,
                "reference_bid_notice_id": reference_bid_notice_id,
                "observation_started_at": analysis["market_entry"]["observation_started_at"],
            },
            "summary": {
                "award_event_count": total_items,
                "unique_project_count": total_items,
                "contract_event_count": contract_event_count,
                "contract_version_count": contract_version_count,
                "attributed_award_event_count": _number(attributed_event_total),
                "first_award_date": metrics.get("first_award_date"),
                "latest_award_date": metrics.get("latest_award_date"),
                "active_years": metrics.get("active_years", []),
                "active_year_count": metrics.get("active_year_count", 0),
                "consecutive_active_years": metrics.get("consecutive_active_years", 0),
                "similar_amount_event_count": sum(
                    item["is_similar_amount"] is True for item in event_items
                ) if target_amount is not None else None,
                "total_attributed_contract_amount": total_attributed_contract_amount,
                "amount_completeness": relationship_amount_completeness,
            },
            "project_type_distribution": project_distribution,
            "amount_distribution": amount_distribution,
            "yearly_activity": yearly_activity,
            "annual_activity": annual_activity,
            "events": paged_events,
            "pagination": {
                "page": page, "page_size": page_size, "total_items": total_items,
                "total_pages": (total_items + page_size - 1) // page_size,
            },
            "data_completeness": analysis["data_completeness"],
            "timings": {
                "total_ms": round((time.perf_counter() - started) * 1000, 3),
                "cache_hit": False,
            },
        },
    )
    _ORGANIZATION_COMPANY_FIELD_CACHE[cache_key] = (
        time.monotonic(), result.model_copy(deep=True),
    )
    return result


async def execute_organization_company_relationship(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: OrganizationFieldEventReader | None = None,
) -> CapabilityResult:
    """Return complete company×organization history without field filtering."""
    history_inputs = {
        "organization_code": inputs["organization_code"],
        "business_registration_number": inputs["business_registration_number"],
        "work_type": inputs.get("work_type"),
        "period_years": inputs.get("period_years", 10),
        "page": inputs.get("page", 1),
        "page_size": inputs.get("page_size", 20),
    }
    result = await execute_organization_company_field_relationship(
        catalog,
        "get_organization_company_field_relationship",
        history_inputs,
        reader=reader,
    )
    result.capability_id = capability_id
    result.outcome["relationship_type"] = "organization_history"
    result.outcome["analysis_basis"].update({
        "field_filter_applied": False,
        "similarity_assessment_applied": False,
    })
    result.outcome.pop("field", None)
    result.outcome["yearly_activity"] = result.outcome.pop("annual_activity")
    for event in result.outcome["events"]:
        event["organization_match"] = True
        event.pop("field_match_reasons", None)
    properties = {
        "organization_company_relationship_id": (
            f"{history_inputs['organization_code']}:"
            f"{''.join(character for character in str(history_inputs['business_registration_number']) if character.isdigit())}"
        ),
        "organization_code": history_inputs["organization_code"],
        "company_number": "".join(
            character for character in str(history_inputs["business_registration_number"])
            if character.isdigit()
        ),
        "award_event_count": result.outcome["summary"]["award_event_count"],
        "unique_project_count": result.outcome["summary"]["unique_project_count"],
        "contract_event_count": result.outcome["summary"]["contract_event_count"],
        "contract_version_count": result.outcome["summary"]["contract_version_count"],
    }
    provenance = result.objects[0].provenance if result.objects else []
    result.objects = [MaterializedObject(
        ontology="public_procurement",
        object_type="organization_company_relationship",
        object_id=properties["organization_company_relationship_id"],
        properties=properties,
        provenance=provenance,
        property_provenance={key: provenance for key in properties},
    )]
    return result


async def execute_company_similar_project_experience(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: CompanySimilarProjectExperienceReader | None = None,
) -> CapabilityResult:
    """Find company experience sharing any current mandatory industry/license."""
    started = time.perf_counter()
    reference_bid_notice_id = str(inputs["reference_bid_notice_id"])
    company_number = "".join(
        character for character in str(inputs["business_registration_number"])
        if character.isdigit()
    )
    return await _execute_company_similar_project_experience_body(
        catalog, capability_id, inputs, started=started,
        reference_bid_notice_id=reference_bid_notice_id,
        company_number=company_number, reader=reader,
    )


async def _execute_company_similar_project_experience_body(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    started: float, reference_bid_notice_id: str, company_number: str,
    reader: CompanySimilarProjectExperienceReader | None,
) -> CapabilityResult:
    period_years = int(inputs.get("period_years", 10))
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    resolved_reader = reader or CompanySimilarProjectExperienceReader()
    try:
        reference, rows = await asyncio.to_thread(
            resolved_reader.find, catalog,
            reference_bid_notice_id=reference_bid_notice_id,
            business_registration_number=company_number,
            period_years=period_years,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    required_codes = sorted(map(str, reference.get("industry_codes") or []))
    if not required_codes:
        raise CapabilityExecutionError(
            "reference_industry_requirements_unavailable",
            "the reference notice has no complete structured industry/license requirements",
            capability_id=capability_id,
        )
    reference_amount = reference.get("estimated_price") or reference.get("allocated_budget")
    experiences = []
    for row in rows:
        candidate_codes = sorted(map(str, row.get("industry_codes") or []))
        matched_codes = sorted(set(required_codes) & set(candidate_codes))
        amount = (row.get("contract_amount") or row.get("winning_amount")
                  or row.get("estimated_price") or row.get("allocated_budget"))
        amount_score, amount_reason = _amount_similarity(reference_amount, amount)
        share = _number(row.get("participation_share_rate"))
        supplier_count = int(row.get("supplier_count") or 0)
        contract_amount = row.get("contract_amount")
        attributed_amount = None
        if contract_amount is not None:
            if share is not None:
                attributed_amount = _number(
                    Decimal(str(contract_amount)) * Decimal(str(share)) / Decimal("100")
                )
            elif supplier_count == 1:
                attributed_amount = _number(contract_amount)
        comparison = _title_project_comparison(
            str(reference.get("notice_name") or ""), str(row.get("notice_name") or ""),
            trigram_score=(float(row["title_trigram_score"])
                           if row.get("title_trigram_score") is not None else None),
        )
        experiences.append({
            "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
            "notice_published_date": row.get("notice_published_date"),
            "organization_code": row.get("demand_organization_code"),
            "organization_name": row.get("demand_organization_name"),
            "work_type": row.get("work_type"),
            "industry_license_assessment": {
                "required_codes": required_codes, "candidate_codes": candidate_codes,
                "matched_codes": matched_codes, "matched_code_count": len(matched_codes),
                "required_code_count": len(required_codes),
                "coverage_ratio": round(len(matched_codes) / len(required_codes), 6),
                "any_required_code_matched": bool(matched_codes),
                "all_required_codes_included": len(matched_codes) == len(required_codes),
                "status": "matched", "rule": "any_required_industry_code_overlap",
            },
            "award_date": row.get("award_date"), "contract_date": row.get("contract_date"),
            "winning_amount": _number(row.get("winning_amount")),
            "contract_amount": _number(contract_amount),
            "attributed_contract_amount": attributed_amount,
            "attributed_contract_amount_completeness": (
                "complete" if attributed_amount is not None
                else "partial" if contract_amount is not None else "unknown"
            ),
            "company_role": (
                "sole" if supplier_count == 1
                else "consortium_lead" if row.get("supplier_role_name") in {
                    "대표사", "주계약자", "대표업체",
                } else "consortium_member" if supplier_count > 1 else "award_winner"
            ),
            "share_percent": share,
            "project_type": _primary_project_type(str(row.get("notice_name") or "")),
            "is_similar_amount": amount_score >= 0.5 if reference_amount and amount else None,
            "similar_amount_reason": amount_reason, **comparison,
        })
    experiences.sort(
        key=lambda item: item.get("contract_date") or item.get("award_date")
        or item.get("notice_published_date") or date.min, reverse=True,
    )
    total_items = len(experiences)
    eligible = [item for item in experiences if item["comparison_eligible"]]
    quality_counts = {
        quality: sum(item["comparison_quality"] == quality for item in experiences)
        for quality in ("strong", "limited", "reference_only")
    }
    offset = (page - 1) * page_size
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.get_company_similar_project_experience",
        mapping="public_procurement_market_context", observed_at=datetime.now(timezone.utc),
        record_keys=[reference_bid_notice_id, company_number],
    )
    properties = {
        "company_similar_project_experience_id": f"{reference_bid_notice_id}:{company_number}",
        "reference_bid_notice_id": reference_bid_notice_id,
        "company_number": company_number, "experience_count": total_items,
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement", object_type="company_similar_project_experience",
            object_id=properties["company_similar_project_experience_id"],
            properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )],
        outcome={
            "reference_bid_notice_id": reference_bid_notice_id,
            "company": {"business_registration_number": company_number},
            "analysis_basis": {
                "period_years": period_years, "work_type": reference.get("work_type"),
                "required_industries": [
                    {"code": code, "name": (reference.get("industry_names") or {}).get(code)}
                    for code in required_codes
                ],
                "matching_rule": "any_required_industry_code_overlap",
                "title_keyword_filter_applied": False,
                "semantic_similarity_applied": False,
                "title_comparison_profile": "normalized_token_and_character_trigram_v1",
                "title_trigram_similarity_threshold": TITLE_TRIGRAM_SIMILARITY_THRESHOLD,
            },
            "summary": {
                "candidate_count": total_items, "event_count": len(eligible),
                "strong_event_count": quality_counts["strong"],
                "limited_event_count": quality_counts["limited"],
                "reference_only_event_count": quality_counts["reference_only"],
                "similar_amount_event_count": sum(
                    item["is_similar_amount"] is True for item in eligible
                ),
            },
            "experiences": experiences[offset:offset + page_size],
            "pagination": {
                "page": page, "page_size": page_size, "total_items": total_items,
                "total_pages": (total_items + page_size - 1) // page_size,
            },
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


def _amount_completeness(statuses: list[str]) -> str:
    if not statuses or all(status == "unknown" for status in statuses):
        return "unknown"
    if all(status == "complete" for status in statuses):
        return "complete"
    return "partial"


def _fiscal_period_start(as_of: date | datetime, period_years: int) -> date:
    """Return January 1 of the oldest included calendar fiscal year."""
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    return date(as_of_date.year - period_years + 1, 1, 1)


def _normalized_category(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def _effective_large_category(row: dict[str, Any]) -> str | None:
    if str(row.get("work_type") or "") == "construction":
        return _normalized_category(row.get("procurement_classification_name"))
    return _normalized_category(row.get("procurement_large_classification_name"))


def _effective_middle_category(row: dict[str, Any]) -> str | None:
    if str(row.get("work_type") or "") == "construction":
        return None
    return _normalized_category(row.get("procurement_middle_classification_name"))


def _filter_profile_rows(
    rows: list[dict[str, Any]], *, large_category: str | None,
    middle_category: str | None, field_code: str | None, work_type: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    for row in rows:
        if work_type and str(row.get("work_type") or "unknown") != work_type:
            continue
        field_identity = _procurement_field_identity(row)
        if large_category or middle_category or field_code:
            if large_category == "미분류":
                if field_identity is not None or middle_category or field_code:
                    continue
                filtered.append(row)
                continue
            if field_identity is None:
                continue
            if large_category and _effective_large_category(row) != large_category:
                continue
            if middle_category and _effective_middle_category(row) != middle_category:
                continue
            if field_code and str(row.get("procurement_classification_number")) != field_code:
                continue
        filtered.append(row)
    return filtered


def _contract_project_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identify one logical contract relationship independently of its versions."""
    notice_id = str(row.get("bid_notice_id") or "").strip()
    project_id = notice_id if notice_id and not notice_id.startswith("contract:") else str(
        row.get("event_key") or notice_id
    )
    return (
        str(row.get("organization_code") or ""),
        str(row.get("company_number") or ""),
        str(row.get("work_type") or "unknown"),
        project_id,
    )


def _collapse_profile_contract_versions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest contract version and retain the raw version count."""
    contracts: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    result = []
    for row in rows:
        if row.get("activity_type") != "contract":
            result.append(row)
            continue
        contracts.setdefault(_contract_project_key(row), []).append(row)
    for versions in contracts.values():
        latest = max(versions, key=lambda row: row.get("activity_date") or date.min)
        collapsed = dict(latest)
        collapsed["contract_version_count"] = sum(
            int(row.get("contract_version_count") or 1) for row in versions
        )
        collapsed["contract_version_dates"] = sorted({
            row["activity_date"] for row in versions if row.get("activity_date")
        })
        result.append(collapsed)
    return result


def _drilldown_field_distribution(
    fields: list[dict[str, Any]], *, large_category: str | None,
    middle_category: str | None, field_code: str | None, work_type: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    if large_category == "미분류":
        return "unclassified", fields
    if work_type == "construction":
        return ("detail" if field_code else "construction_field"), fields
    if field_code:
        return "detail", fields
    if middle_category:
        return "field", fields
    group_property = "middle_category" if large_category else "large_category"
    level = "middle" if large_category else "large"
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for field in fields:
        category = _normalized_category(field.get(group_property)) or "미분류"
        field_work_types = list(field.get("work_types") or [])
        unclassified_work_type = (
            field_work_types[0] if category == "미분류" and len(field_work_types) == 1
            else None
        )
        group_key = (category, unclassified_work_type)
        item = grouped.setdefault(group_key, {
            group_property: category, "event_count": 0,
            "participation_count": 0, "award_event_count": 0,
            "contract_event_count": 0, "attributed_contract_amount": Decimal("0"),
            "work_types": set(),
        })
        if category == "미분류":
            item.update({
                "field_code": None, "field_name": None,
                "middle_category": None, "classification_source": "unclassified",
            })
        for count_field in (
            "event_count", "participation_count", "award_event_count", "contract_event_count",
        ):
            item[count_field] += int(field.get(count_field) or 0)
        item["attributed_contract_amount"] += Decimal(
            str(field.get("attributed_contract_amount") or 0)
        )
        item["work_types"].update(field.get("work_types") or [])
    total_amount = sum(
        (item["attributed_contract_amount"] for item in grouped.values()), Decimal("0")
    )
    distribution = []
    for item in grouped.values():
        amount = item["attributed_contract_amount"]
        item["attributed_contract_amount"] = _number(amount)
        item["amount_share"] = round(float(amount / total_amount), 6) if total_amount else None
        item["work_types"] = sorted(item["work_types"])
        distribution.append(item)
    distribution.sort(key=lambda item: item["event_count"], reverse=True)
    return level, distribution


def _profile_aggregate(
    rows: list[dict[str, Any]], *, relationship_dimension: str,
) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]],
]:
    key_field = "company_number" if relationship_dimension == "company" else "organization_code"
    name_field = "company_name" if relationship_dimension == "company" else "organization_name"
    relationships: dict[str, dict[str, Any]] = {}
    yearly: dict[int, dict[str, Any]] = {}
    field_totals: dict[str, dict[str, Any]] = {}
    project_type_totals: dict[str, dict[str, Any]] = {}
    work_type_totals: dict[str, dict[str, Any]] = {}
    notice_ids = set()
    classified_notice_ids = set()
    participant_event_keys: set[tuple[str, str]] = set()
    award_event_keys: set[str] = set()
    contract_event_keys: set[str] = set()
    project_keys: set[tuple[str, str]] = set()
    contract_version_count = 0
    companies = set()
    organizations = set()
    total_amount = Decimal("0")
    amount_statuses: list[str] = []
    for row in rows:
        key = str(row.get(key_field) or "")
        if not key:
            continue
        activity_type = str(row["activity_type"])
        activity_date = row["activity_date"]
        amount = row.get("attributed_contract_amount")
        completeness = str(row.get("amount_completeness") or "unknown")
        work_type = str(row.get("work_type") or "unknown")
        relationship = relationships.setdefault(key, {
            key_field: key,
            name_field: row.get(name_field),
            "participation_count": 0, "award_event_count": 0,
            "contract_event_count": 0,
            "contract_version_count": 0, "project_keys": set(),
            "total_attributed_contract_amount": Decimal("0"),
            "amount_statuses": [], "dates": [], "years": set(),
            "yearly": {}, "fields": {}, "project_types": {},
            "representative_notices": [],
        })
        if row.get(name_field):
            relationship[name_field] = row[name_field]
        count_field = {
            "participation": "participation_count",
            "award": "award_event_count",
            "contract": "contract_event_count",
        }[activity_type]
        relationship[count_field] += 1
        relationship["project_keys"].add(str(row["bid_notice_id"]))
        project_keys.add((key, str(row["bid_notice_id"])))
        relationship_dates = (
            row.get("contract_version_dates") or [activity_date]
            if activity_type == "contract" else [activity_date]
        )
        relationship["dates"].extend(relationship_dates)
        relationship["years"].update(value.year for value in relationship_dates)
        year_item = relationship["yearly"].setdefault(activity_date.year, {
            "year": activity_date.year, "participation_count": 0,
            "award_event_count": 0, "contract_event_count": 0,
            "attributed_contract_amount": Decimal("0"), "amount_statuses": [],
        })
        year_item[count_field] += 1
        if activity_type == "contract":
            versions = int(row.get("contract_version_count") or 1)
            relationship["contract_version_count"] += versions
            contract_version_count += versions
            relationship["amount_statuses"].append(completeness)
            year_item["amount_statuses"].append(completeness)
            amount_statuses.append(completeness)
            contract_event_keys.add(str(row["event_key"]))
            if amount is not None:
                decimal_amount = Decimal(str(amount))
                relationship["total_attributed_contract_amount"] += decimal_amount
                year_item["attributed_contract_amount"] += decimal_amount
                total_amount += decimal_amount
        elif activity_type == "award":
            award_event_keys.add(str(row["event_key"]))
        else:
            participant_event_keys.add((key, str(row["event_key"])))
        notice_ids.add(str(row["bid_notice_id"]))
        companies.add(str(row.get("company_number") or ""))
        organizations.add(str(row.get("organization_code") or ""))
        relationship["representative_notices"].append({
            "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
            "activity_type": activity_type, "activity_date": activity_date,
            "amount": _number(amount if activity_type == "contract" else row.get("event_amount")),
        })
        field_identity = _procurement_field_identity(row)
        if field_identity:
            classified_notice_ids.add(str(row["bid_notice_id"]))
        else:
            field_identity = {
                "code": None, "name": None, "large_category": "미분류",
                "middle_category": None, "detailed_items": [], "source": "unclassified",
            }
        field_key = field_identity["code"] or f"__unclassified__:{work_type}"
        relation_field = relationship["fields"].setdefault(field_key, {
                **field_identity, "event_keys": set(), "amount": Decimal("0"),
        })
        for category in ("name", "large_category", "middle_category"):
            if field_identity[category] and not relation_field[category]:
                relation_field[category] = field_identity[category]
        if field_identity["detailed_items"] and not relation_field["detailed_items"]:
            relation_field["detailed_items"] = field_identity["detailed_items"]
        relation_field["event_keys"].add(str(row["bid_notice_id"]))
        if activity_type == "contract" and amount is not None:
            relation_field["amount"] += Decimal(str(amount))
        field = field_totals.setdefault(field_key, {
            "field_code": field_identity["code"], "field_name": field_identity["name"],
            "large_category": field_identity["large_category"],
            "middle_category": field_identity["middle_category"],
            "detailed_items": field_identity["detailed_items"],
            "classification_source": field_identity["source"],
            "work_types": set(),
            "event_keys": set(), "participation_count": 0,
            "award_event_count": 0, "contract_event_count": 0,
            "attributed_contract_amount": Decimal("0"),
        })
        for target, source in (
            ("field_name", "name"), ("large_category", "large_category"),
            ("middle_category", "middle_category"),
        ):
            if field_identity[source] and not field[target]:
                field[target] = field_identity[source]
        if field_identity["detailed_items"] and not field["detailed_items"]:
            field["detailed_items"] = field_identity["detailed_items"]
        event_key = (key, str(row["bid_notice_id"]))
        field["event_keys"].add(event_key)
        field["work_types"].add(work_type)
        field[count_field] += 1
        if activity_type == "contract" and amount is not None:
            field["attributed_contract_amount"] += Decimal(str(amount))
        project_type = _primary_project_type(str(row.get("notice_name") or ""))
        relation_project = relationship["project_types"].setdefault(project_type, {
            "project_type": project_type, "project_type_name": _project_type_label(project_type),
            "event_keys": set(), "amount": Decimal("0"),
        })
        relation_project["event_keys"].add(str(row["bid_notice_id"]))
        project = project_type_totals.setdefault(project_type, {
            "project_type": project_type, "project_type_name": _project_type_label(project_type),
            "event_keys": set(), "attributed_contract_amount": Decimal("0"),
        })
        project["event_keys"].add((key, str(row["bid_notice_id"])))
        if activity_type == "contract" and amount is not None:
            decimal_amount = Decimal(str(amount))
            relation_project["amount"] += decimal_amount
            project["attributed_contract_amount"] += decimal_amount
        work = work_type_totals.setdefault(work_type, {
            "work_type": work_type, "work_type_name": _work_type_label(work_type),
            "event_keys": set(), "participation_keys": set(),
            "award_event_keys": set(), "contract_event_keys": set(),
            "attributed_contract_amount": Decimal("0"),
        })
        work_event_key: Any = str(row["event_key"])
        if activity_type == "participation":
            work_event_key = (key, work_event_key)
        work["event_keys"].add((activity_type, work_event_key))
        work[{
            "participation": "participation_keys",
            "award": "award_event_keys",
            "contract": "contract_event_keys",
        }[activity_type]].add(work_event_key)
        if activity_type == "contract" and amount is not None:
            work["attributed_contract_amount"] += Decimal(str(amount))

        global_year = yearly.setdefault(activity_date.year, {
            "year": activity_date.year, "notice_ids": set(), "company_ids": set(),
            "award_event_keys": set(), "contract_event_keys": set(),
            "attributed_contract_amount": Decimal("0"), "amount_statuses": [],
        })
        global_year["notice_ids"].add(str(row["bid_notice_id"]))
        global_year["company_ids"].add(str(row.get("company_number") or ""))
        if activity_type == "award":
            global_year["award_event_keys"].add(str(row["event_key"]))
        elif activity_type == "contract":
            global_year["contract_event_keys"].add(str(row["event_key"]))
            global_year["amount_statuses"].append(completeness)
            if amount is not None:
                global_year["attributed_contract_amount"] += Decimal(str(amount))

    relationship_items = []
    for relationship in relationships.values():
        relation_yearly = []
        for value in sorted(relationship.pop("yearly").values(), key=lambda x: x["year"]):
            statuses = value.pop("amount_statuses")
            value["attributed_contract_amount"] = _number(value["attributed_contract_amount"])
            value["amount_completeness"] = _amount_completeness(statuses)
            relation_yearly.append(value)
        statuses = relationship.pop("amount_statuses")
        dates = relationship.pop("dates")
        years = sorted(relationship.pop("years"))
        major_fields = []
        for field in relationship.pop("fields").values():
            major_fields.append({
                "code": field["code"], "name": field["name"],
                "event_count": len(field["event_keys"]), "amount": _number(field["amount"]),
            })
        major_fields.sort(key=lambda item: item["event_count"], reverse=True)
        project_types = []
        for project in relationship.pop("project_types").values():
            project_types.append({
                "project_type": project["project_type"],
                "project_type_name": project["project_type_name"],
                "event_count": len(project["event_keys"]), "amount": _number(project["amount"]),
            })
        project_types.sort(key=lambda item: item["event_count"], reverse=True)
        relationship.update({
            "total_attributed_contract_amount": _number(
                relationship["total_attributed_contract_amount"]
            ),
            "amount_completeness": _amount_completeness(statuses),
            "first_activity_date": min(dates) if dates else None,
            "latest_activity_date": max(dates) if dates else None,
            "active_years": years, "active_year_count": len(years),
            "unique_project_count": len(relationship.pop("project_keys")),
            "yearly_activity": relation_yearly,
            "major_fields": major_fields,
            "project_type_distribution": project_types,
            "representative_notices": sorted(
                relationship["representative_notices"],
                key=lambda item: item["activity_date"], reverse=True,
            )[:3],
        })
        relationship_items.append(relationship)
    yearly_items = []
    for year in sorted(yearly, reverse=True):
        value = yearly[year]
        yearly_items.append({
            "year": year, "notice_count": len(value["notice_ids"]),
            "award_event_count": len(value["award_event_keys"]),
            "contract_event_count": len(value["contract_event_keys"]),
            "company_count": len(value["company_ids"] - {""}),
            "attributed_contract_amount": _number(value["attributed_contract_amount"]),
            "amount_completeness": _amount_completeness(value["amount_statuses"]),
        })
    field_items = []
    for value in field_totals.values():
        amount = value.pop("attributed_contract_amount")
        value["work_types"] = sorted(value["work_types"])
        value["event_count"] = len(value.pop("event_keys"))
        value["attributed_contract_amount"] = _number(amount)
        value["amount_share"] = (
            round(float(amount / total_amount), 6) if total_amount else None
        )
        field_items.append(value)
    summary = {
        "notice_count": len(notice_ids), "participation_count": len(participant_event_keys),
        "award_event_count": len(award_event_keys),
        "contract_event_count": len(contract_event_keys),
        "contract_version_count": contract_version_count,
        "unique_project_count": len(project_keys),
        "company_count": len(companies - {""}),
        "organization_count": len(organizations - {""}),
        "total_attributed_contract_amount": _number(total_amount),
        "amount_completeness": _amount_completeness(amount_statuses),
        "classified_notice_count": len(classified_notice_ids),
        "field_classification_completeness": (
            "complete" if notice_ids and classified_notice_ids == notice_ids
            else "partial" if classified_notice_ids else "unknown"
        ),
    }
    project_type_items = []
    for value in project_type_totals.values():
        project_type_items.append({
            "project_type": value["project_type"],
            "project_type_name": value["project_type_name"],
            "event_count": len(value["event_keys"]),
            "attributed_contract_amount": _number(value["attributed_contract_amount"]),
        })
    work_type_items = []
    for value in work_type_totals.values():
        work_type_items.append({
            "work_type": value["work_type"], "work_type_name": value["work_type_name"],
            "event_count": len(value["event_keys"]),
            "participation_count": len(value["participation_keys"]),
            "award_event_count": len(value["award_event_keys"]),
            "contract_event_count": len(value["contract_event_keys"]),
            "attributed_contract_amount": _number(value["attributed_contract_amount"]),
        })
    return (
        summary, relationship_items, yearly_items, field_items,
        project_type_items, work_type_items,
    )


def _shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _rolling_12m_supplier_entry(
    rows: list[dict[str, Any]], first_relationship_dates: dict[str, date],
    history_available_from: date | None, *, period_to: date,
) -> dict[str, Any]:
    """Classify unique suppliers in a fixed current/prior 12-month contract window."""
    period_from = _shift_years(period_to, -1)
    comparison_period_from = _shift_years(period_to, -2)
    current_companies: set[str] = set()
    comparison_companies: set[str] = set()
    for row in rows:
        if row.get("activity_type") != "contract":
            continue
        company_number = str(row.get("company_number") or "").strip()
        if not company_number:
            continue
        version_dates = row.get("contract_version_dates") or []
        contract_date = min(version_dates) if version_dates else row.get("activity_date")
        if not contract_date:
            continue
        if period_from <= contract_date < period_to:
            current_companies.add(company_number)
        elif comparison_period_from <= contract_date < period_from:
            comparison_companies.add(company_number)
    first_observed = set()
    reentering = set()
    incumbent = set()
    for company_number in current_companies:
        first_date = first_relationship_dates.get(company_number)
        if first_date is not None and period_from <= first_date < period_to:
            first_observed.add(company_number)
        elif company_number not in comparison_companies:
            reentering.add(company_number)
        else:
            incumbent.add(company_number)
    total = len(current_companies)
    entry_count = len(first_observed) + len(reentering)
    return {
        "window_months": 12,
        "period_from": period_from, "period_to": period_to,
        "comparison_period_from": comparison_period_from,
        "comparison_period_to": period_from,
        "first_observed_company_count": len(first_observed),
        "reentering_company_count": len(reentering),
        "incumbent_company_count": len(incumbent),
        "total_company_count": total,
        "first_observed_company_rate": round(len(first_observed) / total, 6) if total else None,
        "entry_and_reentry_rate": round(entry_count / total, 6) if total else None,
        "history_from": history_available_from,
        "history_basis": "current_5_fiscal_years",
        "minimum_sample_size": 10,
        "sample_sufficient": total >= 10,
    }


async def _execute_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    profile_type: str, reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_years = int(inputs.get("period_years", 5))
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    sort_by = str(inputs.get("sort_by", "contract_amount"))
    if sort_by not in {"contract_amount", "contract_count", "award_count", "latest_activity"}:
        raise CapabilityExecutionError(
            "invalid_sort_by", f"unsupported sort_by '{sort_by}'",
            capability_id=capability_id,
        )
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    work_type = str(inputs.get("work_type") or "").strip() or None
    allowed_work_types = {"goods", "service", "construction", "foreign", "other", "unknown"}
    if work_type and work_type not in allowed_work_types:
        raise CapabilityExecutionError(
            "invalid_work_type", f"unsupported work_type '{work_type}'",
            capability_id=capability_id,
        )
    period_to = date.today() + timedelta(days=1)
    period_from = _fiscal_period_start(date.today(), period_years)
    entry_period_to = date.today()
    entry_comparison_from = _shift_years(entry_period_to, -2)
    entry_history_from = _fiscal_period_start(date.today(), 5)
    source_period_from = min(period_from, entry_comparison_from)
    organization_code = (
        str(inputs["organization_code"]) if profile_type == "organization" else None
    )
    company_number = (
        "".join(character for character in str(inputs["business_registration_number"])
                if character.isdigit()) if profile_type == "company" else None
    )
    resolved_reader = reader or ProcurementProfileReader()
    history_result: tuple[dict[str, date], date | None] | None = None
    try:
        activities_task = asyncio.to_thread(
            resolved_reader.activities, catalog, organization_code=organization_code,
            company_numbers=[company_number] if company_number else [],
            period_from=source_period_from, period_to=period_to,
        )
        history_method = (
            getattr(resolved_reader, "organization_award_history", None)
            if profile_type == "organization" else None
        )
        if history_method is not None:
            rows, history_result = await asyncio.gather(
                activities_task,
                asyncio.to_thread(
                    history_method, catalog, organization_code=str(organization_code),
                    history_from=entry_history_from,
                ),
            )
        else:
            rows = await activities_task
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    rows = _filter_profile_rows(
        rows, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    rows = _collapse_profile_contract_versions(rows)
    profile_rows = [
        row for row in rows if row.get("activity_date") and row["activity_date"] >= period_from
    ]
    incumbent_share = None
    if profile_type == "organization":
        try:
            if history_result is None:
                relationship_rows = [
                    row for row in rows
                    if row.get("activity_type") in {"award", "contract"}
                    and row.get("company_number") and row.get("activity_date")
                ]
                first_dates: dict[str, date] = {}
                for row in relationship_rows:
                    company = str(row["company_number"])
                    observed = row["activity_date"]
                    first_dates[company] = min(first_dates.get(company, observed), observed)
                history_from = entry_history_from
            else:
                first_dates, history_from = history_result
            incumbent_share = _rolling_12m_supplier_entry(
                rows, first_dates, history_from, period_to=entry_period_to,
            )
        except (ValueError, psycopg.Error, RuntimeError) as exc:
            raise CapabilityExecutionError(
                "database_source_error", str(exc), capability_id=capability_id,
                source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
            ) from exc
    dimension = "company" if profile_type == "organization" else "organization"
    summary, relationships, yearly_activity, fields, project_types, work_types = (
        _profile_aggregate(
        profile_rows, relationship_dimension=dimension,
        )
    )
    if incumbent_share is not None:
        summary["rolling_12m_supplier_entry"] = incumbent_share
    field_distribution_level, field_distribution = _drilldown_field_distribution(
        fields, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    sort_fields = {
        "contract_amount": "total_attributed_contract_amount",
        "contract_count": "contract_event_count",
        "award_count": "award_event_count",
        "latest_activity": "latest_activity_date",
    }
    relationships.sort(
        key=lambda item: item.get(sort_fields[sort_by]) or (date.min if sort_by == "latest_activity" else 0),
        reverse=True,
    )
    total_items = len(relationships)
    offset = (page - 1) * page_size
    paged = relationships[offset:offset + page_size]
    missing_reasons = []
    if summary["amount_completeness"] != "complete":
        missing_reasons.append("some_contract_amounts_not_attributable")
    identity = (
        {"code": organization_code, "name": next((row.get("organization_name") for row in profile_rows if row.get("organization_name")), None)}
        if profile_type == "organization" else
        {"business_registration_number": company_number,
         "name": next((row.get("company_name") for row in profile_rows if row.get("company_name")), None)}
    )
    object_type = f"{profile_type}_procurement_profile"
    object_id = organization_code or company_number
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime", operation=f"market_context.{capability_id}",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[str(object_id)],
    )
    properties = {
        f"{object_type}_id": str(object_id),
        "relationship_count": total_items,
    }
    outcome = {
        profile_type: identity,
        "summary": summary,
        f"{dimension}_relationships": paged,
        "yearly_activity": yearly_activity,
        "field_distribution": field_distribution,
        "field_distribution_level": field_distribution_level,
        "field_hierarchy_depth": 1 if work_type == "construction" else 3,
        "project_type_distribution": sorted(
            project_types, key=lambda item: item["event_count"], reverse=True,
        ),
        "work_type_distribution": sorted(
            work_types, key=lambda item: item["event_count"], reverse=True,
        ),
        "pagination": {
            "page": page, "page_size": page_size, "total_items": total_items,
            "total_pages": (total_items + page_size - 1) // page_size,
            "sort_by": sort_by,
        },
        "analysis_basis": {
            "period_from": period_from, "period_to": period_to - timedelta(days=1),
            "period_years": period_years,
            "period_type": "calendar_fiscal_years",
            "amount_basis": "attributed_contract_amount",
            "event_deduplication": "award_contract_linked_and_contract_versions_merged",
            "field_filter": {
                "large_category": large_category,
                "middle_category": middle_category,
                "field_code": field_code,
                "field_name": next((
                    row.get("procurement_classification_name") for row in profile_rows
                    if field_code and str(row.get("procurement_classification_number")) == field_code
                    and row.get("procurement_classification_name")
                ), None),
            },
            "work_type": work_type,
        },
        "data_completeness": {
            "status": "partial" if missing_reasons else "complete",
            "missing_reasons": missing_reasons,
        },
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    }
    if profile_type == "company":
        outcome["recent_activity"] = sorted(
            [{
                "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
                "activity_type": row["activity_type"], "activity_date": row["activity_date"],
                "organization_code": row.get("organization_code"),
                "organization_name": row.get("organization_name"),
                "work_type": row.get("work_type"),
            } for row in profile_rows], key=lambda item: item["activity_date"], reverse=True,
        )[:20]
    return CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement", object_type=object_type,
            object_id=str(object_id), properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )], outcome=outcome,
    )


async def execute_organization_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    return await _execute_procurement_profile(
        catalog, capability_id, inputs, profile_type="organization", reader=reader,
    )


async def execute_company_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    return await _execute_procurement_profile(
        catalog, capability_id, inputs, profile_type="company", reader=reader,
    )


async def execute_bid_notice_relationship_context(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"])
    history_years = int(inputs.get("relationship_history_years", 5))
    resolved_reader = reader or ProcurementProfileReader()
    try:
        notice, participant_rows = await asyncio.to_thread(
            resolved_reader.bid_context, catalog, bid_notice_id=bid_notice_id,
        )
        cutoff = notice["notice_published_date"]
        period_from = _fiscal_period_start(cutoff, history_years)
        company_numbers = sorted({
            str(row["company_number"]) for row in participant_rows if row.get("company_number")
        })
        prior_rows = await asyncio.to_thread(
            resolved_reader.activities, catalog,
            organization_code=str(notice["organization_code"]),
            company_numbers=company_numbers,
            period_from=period_from, period_to=cutoff,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    _, prior_relationships, _, _, _, _ = _profile_aggregate(
        prior_rows, relationship_dimension="company",
    )
    prior_by_company = {
        item["company_number"]: item for item in prior_relationships
    }
    participants = []
    for row in participant_rows:
        company_number = str(row["company_number"])
        current_contract = None
        if row.get("contract_date"):
            current_contract = {
                "contracted": True, "contract_date": row["contract_date"],
                "contract_amount": _number(row.get("contract_amount")),
                "attributed_contract_amount": _number(row.get("attributed_contract_amount")),
                "company_role": row.get("company_role"),
                "share_percent": _number(row.get("share_percent")),
                "amount_completeness": row.get("amount_completeness"),
            }
        current_award = {
            "awarded": bool(row.get("award_date")), "award_date": row.get("award_date"),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        }
        prior = prior_by_company.get(company_number)
        participants.append({
            "business_registration_number": company_number,
            "company_name": row.get("company_name"),
            "opening_rank": row.get("opening_rank"),
            "bid_amount": _number(row.get("bid_amount")),
            "bid_rate": _number(row.get("bid_rate")),
            "result": (
                "contracted" if current_contract else
                "awarded" if current_award["awarded"] else "participated"
            ),
            "current_award": current_award,
            "current_contract": current_contract,
            "prior_organization_relationship": (
                {key: value for key, value in prior.items() if key not in {
                    "company_number", "company_name", "representative_notices",
                }} if prior else {
                    "participation_count": 0, "award_event_count": 0,
                    "contract_event_count": 0,
                    "total_attributed_contract_amount": 0,
                    "amount_completeness": "unknown", "first_activity_date": None,
                    "latest_activity_date": None, "active_years": [],
                    "active_year_count": 0, "yearly_activity": [],
                }
            ),
        })
    lifecycle = {
        "status": (
            "contracted" if any(item["current_contract"] for item in participants)
            else "awarded" if any(item["current_award"]["awarded"] for item in participants)
            else "opened" if participants else "open"
        ),
        "participation_count": len(participants),
        "award_count": sum(item["current_award"]["awarded"] for item in participants),
        "contract_count": sum(item["current_contract"] is not None for item in participants),
    }
    missing_reasons = []
    if any(
        item["current_contract"] and
        item["current_contract"]["amount_completeness"] != "complete"
        for item in participants
    ):
        missing_reasons.append("some_contract_amounts_not_attributable")
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution", source="teoria_runtime",
        operation="market_context.get_bid_notice_relationship_context",
        mapping="public_procurement_market_context", observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    properties = {
        "bid_notice_relationship_context_id": bid_notice_id,
        "bid_notice_id": bid_notice_id,
        "participant_count": len(participants),
    }
    return CapabilityResult(
        capability_id=capability_id,
        objects=[MaterializedObject(
            ontology="public_procurement", object_type="bid_notice_relationship_context",
            object_id=bid_notice_id, properties=properties, provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        )],
        outcome={
            "bid_notice": {
                "bid_notice_id": bid_notice_id, "notice_name": notice["notice_name"],
                "organization_code": notice["organization_code"],
                "organization_name": notice["organization_name"],
            },
            "lifecycle": lifecycle, "participants": participants,
            "contracts": [
                item["current_contract"] for item in participants if item["current_contract"]
            ],
            "analysis_basis": {
                "period_from": period_from, "period_to": cutoff - timedelta(days=1),
                "period_years": history_years,
                "period_type": "calendar_fiscal_years",
                "prior_relationship_cutoff": cutoff,
                "amount_basis": "attributed_contract_amount",
                "event_deduplication": "award_contract_linked_and_contract_versions_merged",
            },
            "data_completeness": {
                "status": "partial" if missing_reasons else "complete",
                "missing_reasons": missing_reasons,
            },
            "registry_version": catalog.release.version if catalog.release else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


async def _load_company_evidence(
    runner: Any, catalog: RegistryCatalog, rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    semaphore = asyncio.Semaphore(5)

    async def call(capability_id: str, company_number: str) -> CapabilityResult | None:
        async with semaphore:
            try:
                return await runner.run(
                    catalog, capability_id,
                    {"business_registration_number": company_number},
                )
            except CapabilityExecutionError:
                return None

    async def load(company_number: str) -> tuple[str, dict[str, Any]]:
        supplier_result, industry_result = await asyncio.gather(
            call("get_procurement_supplier", company_number),
            call("get_procurement_supplier_industries", company_number),
        )
        supplier = next((
            item for item in (supplier_result.objects if supplier_result else [])
            if item.object_type == "procurement_supplier"
        ), None)
        industries = [
            item for item in (industry_result.objects if industry_result else [])
            if item.object_type == "registered_industry"
        ]
        return company_number, {
            "supplier": dict(supplier.properties) if supplier else None,
            "industries": industries,
            "industries_available": industry_result is not None,
        }

    return dict(await asyncio.gather(*(
        load(str(row["company_number"])) for row in rows
    )))


def _relevant_company_item(
    row: dict[str, Any], notice: dict[str, Any], required_regions: list[dict[str, Any]],
    industry_requirements: list[dict[str, Any]], evidence: dict[str, Any] | None,
    as_of: date, eligibility_reference_date: date, catalog: RegistryCatalog,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    if row.get("similar_participation_count"):
        reason_codes.append("similar_bid_participation_history")
    if row.get("similar_award_count"):
        reason_codes.append("similar_bid_award_history")
    if row.get("similar_contract_count"):
        reason_codes.append("similar_bid_contract_history")
    if row.get("organization_participation_count"):
        reason_codes.append("demand_organization_participation_history")
    if row.get("organization_award_count"):
        reason_codes.append("demand_organization_award_history")
    if row.get("organization_contract_count"):
        reason_codes.append("demand_organization_contract_history")
    latest = row.get("organization_latest_activity_date")
    if latest and latest >= as_of - timedelta(days=RECENT_ACTIVITY_DAYS):
        reason_codes.append("recent_organization_activity")
    supplier = (evidence or {}).get("supplier")
    region = _region_eligibility(required_regions, supplier)
    industry_license = _industry_license_eligibility(
        notice, industry_requirements, evidence, eligibility_reference_date, catalog,
    )
    return {
        "company_number": row["company_number"],
        "company_name": row.get("company_name") or (supplier or {}).get("company_name"),
        "similar_history": {
            "participation_count": int(row.get("similar_participation_count") or 0),
            "award_count": int(row.get("similar_award_count") or 0),
            "contract_count": int(row.get("similar_contract_count") or 0),
            "unified_contract_count": int(row.get("similar_unified_contract_count") or 0),
            "award_amount": _number(row.get("similar_award_amount")),
            "contract_amount": _number(row.get("similar_contract_amount")),
            "contract_amount_basis": "current_contract_amount_supplier_attributed",
            "contract_amount_complete": bool(row.get("similar_contract_amount_complete")),
            "matched_participation_bid_notice_ids": row.get("participation_notice_ids") or [],
            "matched_award_bid_notice_ids": row.get("award_notice_ids") or [],
            "matched_contract_bid_notice_ids": row.get("contract_notice_ids") or [],
            "first_activity_date": row.get("similar_first_activity_date"),
            "latest_activity_date": row.get("similar_latest_activity_date"),
            "activities": row.get("similar_activities") or [],
        },
        "organization_relationship": {
            "organization_code": notice["demand_organization_code"],
            "organization_name": notice["demand_organization_name"],
            "participation_count": int(row.get("organization_participation_count") or 0),
            "award_count": int(row.get("organization_award_count") or 0),
            "contract_count": int(row.get("organization_contract_count") or 0),
            "unified_contract_count": int(row.get("organization_unified_contract_count") or 0),
            "contract_amount": _number(row.get("organization_contract_amount")),
            "contract_amount_basis": "current_contract_amount_supplier_attributed",
            "contract_amount_complete": bool(row.get("contract_amount_complete")),
            "first_activity_date": row.get("organization_first_activity_date"),
            "latest_activity_date": latest,
            "activities": row.get("organization_activities") or [],
        },
        "region_eligibility": region,
        "industry_license_eligibility": industry_license,
        "reason_codes": reason_codes,
        "selection_evidence": {
            "similar_bid_notice_ids": sorted(set(
                (row.get("participation_notice_ids") or [])
                + (row.get("award_notice_ids") or [])
                + (row.get("contract_notice_ids") or [])
            )),
            "has_demand_organization_relationship": any((
                row.get("organization_participation_count"),
                row.get("organization_award_count"),
                row.get("organization_contract_count"),
            )),
        },
    }


def _industry_license_eligibility(
    notice: dict[str, Any], requirement_rows: list[dict[str, Any]],
    evidence: dict[str, Any] | None, reference_date: date, catalog: RegistryCatalog,
) -> dict[str, Any]:
    requirements = [
        MaterializedObject(
            ontology="public_procurement",
            object_type="bid_requirement",
            object_id=str(row["requirement_id"]),
            properties=dict(row),
            provenance=[],
            property_provenance={},
        )
        for row in requirement_rows
    ]
    notice_object = MaterializedObject(
        ontology="public_procurement",
        object_type="bid_notice",
        object_id=str(notice["bid_notice_id"]),
        properties={
            "requirement_expression": notice.get("requirement_expression"),
            "extraction_completeness": notice.get("extraction_completeness"),
        },
        provenance=[],
        property_provenance={},
    )
    snapshot = CompanyEvidenceSnapshot(
        objects=list((evidence or {}).get("industries") or []),
        unavailable_capabilities=(set() if (evidence or {}).get("industries_available") else {
            "get_procurement_supplier_industries"
        }),
    )
    summary, evaluations = evaluate_requirement_category(
        notice_object, requirements, snapshot, reference_date, catalog, "industry_license",
    )
    status = summary.get("outcome") or summary.get("applicability")
    reason_codes = list(dict.fromkeys(
        evaluation.decision.reason_code for evaluation in evaluations
    ))
    if "source_unavailable" in reason_codes:
        status = "unknown"

    required_industries: list[dict[str, Any]] = []
    required_licenses: list[dict[str, Any]] = []
    for requirement in requirements:
        properties = requirement.properties
        value = requirement_value(properties)
        attributes = value.get("attributes") if isinstance(value.get("attributes"), list) else []
        industry_code = next((
            str(item.get("value")) for item in attributes
            if isinstance(item, dict) and item.get("name") == "industry_code" and item.get("value")
        ), None)
        industry_name = next((
            str(item.get("value")) for item in attributes
            if isinstance(item, dict) and item.get("name") == "industry_name" and item.get("value")
        ), None)
        descriptor = {
            "requirement_id": properties.get("requirement_id"),
            "industry_code": industry_code,
            "industry_name": industry_name or value.get("text"),
            "original_text": properties.get("original_text"),
        }
        if properties.get("standard_rule_id") == "has_registered_industry":
            required_industries.append(descriptor)
        else:
            required_licenses.append({
                "requirement_id": properties.get("requirement_id"),
                "name": value.get("text") or properties.get("original_text"),
                "original_text": properties.get("original_text"),
            })

    matched = []
    seen: set[str] = set()
    for evaluation in evaluations:
        if evaluation.decision.outcome != "satisfied":
            continue
        for item in evaluation.decision.evidence:
            key = item.object_id
            if key in seen:
                continue
            seen.add(key)
            matched.append({
                "industry_code": item.properties.get("industry_code"),
                "industry_name": item.properties.get("industry_name"),
                "status_name": item.properties.get("status_name"),
                "registered_at": item.properties.get("registered_at"),
                "valid_until": item.properties.get("valid_until"),
            })
    return {
        "status": status,
        "required_industries": required_industries,
        "required_licenses": required_licenses,
        "matched_industries": matched,
        "matched_licenses": [],
        "unmatched_requirements": [
            {
                "requirement_id": evaluation.requirement.properties.get("requirement_id"),
                "reason_code": evaluation.decision.reason_code,
            }
            for evaluation in evaluations
            if evaluation.decision.outcome != "satisfied"
        ],
        "reason_codes": reason_codes or [
            "no_industry_license_requirement"
            if status == "not_applicable" else "industry_license_extraction_incomplete"
        ],
        "reference_date": reference_date,
    }


def _region_eligibility(
    required_regions: list[dict[str, Any]], supplier: dict[str, Any] | None,
) -> dict[str, Any]:
    required = [
        {"code": item.get("region_code"), "name": item.get("region_name"),
         "business_type_name": item.get("business_type_name")}
        for item in required_regions
    ]
    if not required:
        return {"status": "not_applicable", "required_regions": [],
                "company_locations": [], "reason_code": "no_region_restriction"}
    if not supplier:
        return {"status": "unknown", "required_regions": required,
                "company_locations": [], "reason_code": "company_location_unavailable"}
    location = {
        "location_type": supplier.get("head_office_type_name") or "unknown",
        "region_code": supplier.get("region_code"),
        "region_name": supplier.get("region_name"),
        "base_address": supplier.get("base_address"),
        "source": "pps_procurement_supplier",
    }
    if not any((location["region_code"], location["region_name"], location["base_address"])):
        return {"status": "unknown", "required_regions": required,
                "company_locations": [location], "reason_code": "company_location_unavailable"}
    matched = any(
        (item["code"] and str(item["code"]) == str(location["region_code"]))
        or (item["name"] and _compact(item["name"]) in _compact(
            " ".join(filter(None, [location["region_name"], location["base_address"]]))
        ))
        for item in required
    )
    return {
        "status": "satisfied" if matched else "unsatisfied",
        "required_regions": required,
        "company_locations": [location],
        "reason_code": "region_matched" if matched else "region_mismatched",
    }


def _compact(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _normalized_title(value: str) -> str:
    value = re.sub(
        r"(19|20)\d{2}년|\([^)]*(긴급|재공고|변경|취소)[^)]*\)|\[(긴급|재공고|변경|취소)[^]]*\]",
        " ", value.casefold(),
    )
    return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", value).split())


def _title_tokens(value: str) -> set[str]:
    stopwords = {"사업", "용역", "구매", "공사", "입찰", "공고", "및", "위한"}
    return {token for token in _normalized_title(value).split() if len(token) > 1 and token not in stopwords}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def _character_trigrams(value: str) -> set[str]:
    compact = _compact(_normalized_title(value))
    return {compact[index:index + 3] for index in range(max(0, len(compact) - 2))}


def _title_project_comparison(
    reference_title: str, candidate_title: str, *, trigram_score: float | None = None,
) -> dict[str, Any]:
    reference_tokens = _title_tokens(reference_title)
    candidate_tokens = _title_tokens(candidate_title)
    token_score = _jaccard(reference_tokens, candidate_tokens)
    reference_trigrams = _character_trigrams(reference_title)
    candidate_trigrams = _character_trigrams(candidate_title)
    if trigram_score is None:
        trigram_score = _jaccard(reference_trigrams, candidate_trigrams)
    matched_tokens = sorted(reference_tokens & candidate_tokens)
    title_related = trigram_score >= TITLE_TRIGRAM_SIMILARITY_THRESHOLD
    reference_projects = _project_types(reference_title)
    candidate_projects = _project_types(candidate_title)
    matched_projects = sorted(reference_projects & candidate_projects)
    project_type_match = bool(matched_projects)
    quality = (
        "strong" if title_related and project_type_match
        else "limited" if title_related or project_type_match
        else "reference_only"
    )
    return {
        "title_assessment": {
            "token_score": round(token_score, 6),
            "trigram_score": round(trigram_score, 6),
            "matched_tokens": matched_tokens,
            "title_related": title_related,
        },
        "project_type_match": project_type_match,
        "matched_project_types": matched_projects,
        "comparison_quality": quality,
        "comparison_eligible": quality in {"strong", "limited"},
    }


def _project_types(value: str) -> set[str]:
    patterns = {
        "build": ("구축", "개발", "도입"),
        "improvement": ("고도화", "개선", "재구축"),
        "maintenance": ("유지보수", "유지관리", "운영"),
        "consulting": ("컨설팅", "감리", "설계"),
    }
    compact = _compact(value)
    return {kind for kind, words in patterns.items() if any(word in compact for word in words)}


def _primary_project_type(value: str) -> str:
    compact = _compact(value)
    candidates = {
        "improvement": ("고도화", "개선", "재구축"),
        "maintenance": ("유지보수", "유지관리", "운영"),
        "build": ("구축", "개발", "도입"),
        "consulting": ("컨설팅", "감리", "설계"),
    }
    positions = []
    for kind, words in candidates.items():
        found = [compact.find(word) for word in words if word in compact]
        if found:
            positions.append((min(found), kind))
    return min(positions)[1] if positions else "unknown"


def _project_type_label(value: str) -> str:
    return {
        "build": "구축", "improvement": "개선·고도화",
        "maintenance": "유지관리", "consulting": "컨설팅·감리·설계",
        "unknown": "미분류",
    }[value]


def _work_type_label(value: str) -> str:
    return {
        "goods": "물품", "service": "용역", "construction": "공사",
        "foreign": "외자", "other": "기타", "unknown": "미분류",
    }.get(value, value)


def _procurement_field_identity(row: dict[str, Any]) -> dict[str, Any] | None:
    """Use provider classifications as the field identity; never infer it from a title."""
    code = str(row.get("procurement_classification_number") or "").strip()
    name = str(row.get("procurement_classification_name") or "").strip()
    if not code and not name:
        return None
    is_construction = str(row.get("work_type") or "") == "construction"
    return {
        "code": code or f"name:{name}",
        "name": name or None,
        "large_category": name if is_construction else _normalized_category(
            row.get("procurement_large_classification_name")
        ),
        "middle_category": None if is_construction else _normalized_category(
            row.get("procurement_middle_classification_name")
        ),
        "detailed_items": row.get("purchase_items") or [],
        "source": (
            "construction_work_category" if is_construction
            else "procurement_classification"
        ),
    }


def _organization_field_analysis_basis(
    notice: dict[str, Any], period_years: int,
) -> dict[str, Any]:
    """Expose the exact inputs and boundaries used by company relationship analysis."""
    title = str(notice.get("notice_name") or "")
    fields = _business_fields(title)
    project_kinds = _project_types(title)
    ordered_kinds = [
        kind for kind in ("build", "improvement", "maintenance", "consulting")
        if kind in project_kinds
    ]
    is_information_system = "information_system" in fields or (
        "1468" in set(map(str, notice.get("industry_codes") or [])) and "시스템" in title
    )
    project_types = [
        f"information_system_{kind}" if is_information_system else kind
        for kind in ordered_kinds
    ]
    labels = {
        "build": "구축",
        "improvement": "고도화·개선",
        "maintenance": "유지보수·운영",
        "consulting": "컨설팅·감리·설계",
    }
    project_type_labels = [
        f"정보시스템 {labels[kind]}" if is_information_system else labels[kind]
        for kind in ordered_kinds
    ]
    reference_amount = notice.get("estimated_price") or notice.get("allocated_budget")
    reference_number = _number(reference_amount)
    amount_basis = "estimated_price" if notice.get("estimated_price") is not None else (
        "allocated_budget" if notice.get("allocated_budget") is not None else None
    )
    similar_amount = {
        "amount_basis": amount_basis,
        "reference_amount": reference_number,
        "minimum_amount": None,
        "maximum_amount": None,
        "rule": "0.5x_to_2.0x",
        "comparison_rule": "min(reference,candidate)/max(reference,candidate) >= 0.5",
    }
    if reference_amount:
        similar_amount["minimum_amount"] = _number(Decimal(str(reference_amount)) / Decimal("2"))
        similar_amount["maximum_amount"] = _number(Decimal(str(reference_amount)) * Decimal("2"))

    industries = notice.get("industries") or [
        {"industry_code": code, "industry_name": None}
        for code in notice.get("industry_codes") or []
    ]
    as_of = notice.get("as_of") or date.today()
    period_from = _fiscal_period_start(as_of, period_years)
    period_to = as_of.date() if isinstance(as_of, datetime) else as_of
    return {
        "period_years": period_years,
        "period_type": "calendar_fiscal_years",
        "period_from": period_from,
        "period_to": period_to,
        "work_type": notice.get("work_type"),
        "industries": [
            {"code": str(item["industry_code"]), "name": item.get("industry_name")}
            for item in industries
        ],
        "field": {
            "code": "information_system" if is_information_system else (
                sorted(fields)[0] if fields else None
            ),
            "label": "정보시스템" if is_information_system else None,
        },
        "project_type": {
            "code": ordered_kinds[0] if ordered_kinds else None,
            "label": project_type_labels[0] if project_type_labels else None,
        },
        "project_type_code": project_types[0] if project_types else None,
        "project_type_label": project_type_labels[0] if project_type_labels else None,
        "project_types": project_types,
        "project_type_labels": project_type_labels,
        "similar_amount": similar_amount,
        "similar_amount_range": dict(similar_amount),
    }


def _canonical_contract_notice_number(value: Any) -> str:
    number = str(value or "").strip()
    if number.isdigit() and len(number) == 13 and number.endswith("00"):
        return number[:-2]
    return number


def _organization_relationship_metrics(
    events: list[dict[str, Any]], as_of: date | datetime | None, period_years: int,
) -> dict[str, dict[str, Any]]:
    """Derive field-free organization metrics from already merged award events."""
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of or date.today()
    period_start = _fiscal_period_start(as_of_date, period_years)
    recent_events = [
        event for event in events
        if any(
            period_start <= activity_date < as_of_date
            for activity_date in event.get("activity_dates") or []
        )
    ]
    by_company: dict[str, list[dict[str, Any]]] = {}
    for event in recent_events:
        for company_number in event["members"]:
            by_company.setdefault(company_number, []).append(event)
    metrics: dict[str, dict[str, Any]] = {}
    for company_number, company_events in by_company.items():
        annual: dict[int, dict[str, Any]] = {}
        for event in company_events:
            member = event["members"][company_number]
            annualized_at = member.get("attributed_at") or event.get("awarded_at")
            if annualized_at is None:
                continue
            member_count = len(event["members"])
            year_item = annual.setdefault(annualized_at.year, {
                "year": annualized_at.year,
                "award_event_count": 0,
                "attributed_contract_amount": Decimal("0"),
                "known_amount_count": 0,
                "sole_count": 0,
                "consortium_lead_count": 0,
                "consortium_member_count": 0,
            })
            year_item["award_event_count"] += 1
            attributed_amount = member.get("attributed_amount")
            if attributed_amount is not None:
                year_item["attributed_contract_amount"] += Decimal(str(attributed_amount))
                year_item["known_amount_count"] += 1
            if member_count == 1:
                year_item["sole_count"] += 1
            elif member.get("supplier_role_name") in {"대표사", "주계약자", "대표업체"}:
                year_item["consortium_lead_count"] += 1
            else:
                year_item["consortium_member_count"] += 1
        annual_activity = []
        for year in sorted(annual):
            value = annual[year]
            known_count = value.pop("known_amount_count")
            event_count = value["award_event_count"]
            annual_activity.append({
                **value,
                "attributed_contract_amount": _number(value["attributed_contract_amount"]),
                "amount_completeness": (
                    "complete" if known_count == event_count
                    else "unknown" if known_count == 0
                    else "partial"
                ),
            })
        metrics[company_number] = {
            "same_field_event_count": len(company_events),
            "annual_activity": annual_activity,
        }
    return metrics


def _organization_field_event_analysis(
    rows: list[dict[str, Any]], notice: dict[str, Any], period_years: int,
) -> dict[str, Any]:
    """Unify award and contract rows, then derive explainable market metrics."""
    awards: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    contracts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("source_kind") == "award":
            key = tuple(str(row.get(name) or "") for name in (
                "notice_number", "notice_order", "bid_classification_number", "rebid_number",
            ))
            event = awards.setdefault(key, {
                "event_id": "award:" + ":".join(key),
                "notice_id": row.get("bid_notice_id"),
                "notice_name": row.get("notice_name"),
                "notice_published_date": row.get("notice_published_date"),
                "awarded_at": row.get("event_date"),
                "award_date": row.get("event_date"),
                "contract_date": None,
                "activity_dates": [row.get("event_date")] if row.get("event_date") else [],
                "amount": _number(row.get("event_amount")),
                "award_amount": _number(row.get("event_amount")),
                "contract_amount": None,
                "project_types": sorted(_project_types(str(row.get("notice_name") or ""))),
                "members": {}, "contract_ids": [], "source_kinds": {"award"},
            })
            event["members"][str(row["company_number"])] = {
                "company_number": str(row["company_number"]),
                "company_name": row.get("company_name"), "share_rate": None,
                "supplier_role_name": "award_winner", "attributed_amount": None,
                "attributed_at": None, "contract_activity_dates": [],
            }
        else:
            notice_number = _canonical_contract_notice_number(row.get("notice_number"))
            contract_key = (
                f"notice:{notice_number}" if notice_number else str(
                    row.get("original_contract_number") or row.get("unified_contract_number")
                )
            )
            contracts.setdefault(contract_key, []).append(row)

    award_keys_by_notice: dict[str, list[tuple[str, str, str, str]]] = {}
    for key in awards:
        award_keys_by_notice.setdefault(_canonical_contract_notice_number(key[0]), []).append(key)
    merged_award_keys: set[tuple[str, str, str, str]] = set()
    contract_only_count = 0
    unattributed_contract_count = 0
    for contract_key, contract_rows in contracts.items():
        latest = max(contract_rows, key=lambda row: row.get("event_date") or date.min)
        earliest = min(contract_rows, key=lambda row: row.get("event_date") or date.max)
        first = latest
        member_numbers = {str(row["company_number"]) for row in contract_rows}
        candidates = award_keys_by_notice.get(
            _canonical_contract_notice_number(first.get("notice_number")), [],
        )
        matching = [
            key for key in candidates
            if set(awards[key]["members"]) & member_numbers
        ]
        selected_key = matching[0] if len(matching) == 1 else (
            candidates[0] if len(candidates) == 1 else None
        )
        if selected_key is not None:
            event = awards[selected_key]
            merged_award_keys.add(selected_key)
        else:
            event = {
                "event_id": f"contract:{contract_key}",
                "notice_id": first.get("bid_notice_id"),
                "notice_name": first.get("notice_name"),
                "notice_published_date": first.get("notice_published_date"),
                "awarded_at": earliest.get("event_date"),
                "award_date": None,
                "contract_date": earliest.get("event_date"),
                "activity_dates": sorted({
                    row["event_date"] for row in contract_rows if row.get("event_date")
                }),
                "amount": _number(first.get("event_amount")),
                "award_amount": None,
                "contract_amount": _number(first.get("contract_amount")),
                "project_types": sorted(_project_types(str(first.get("notice_name") or ""))),
                "members": {}, "contract_ids": [], "source_kinds": set(),
            }
            awards[("contract", contract_key, "", "")] = event
            contract_only_count += 1
            if first.get("notice_number") and candidates:
                unattributed_contract_count += 1
        event["source_kinds"].add("contract")
        event["contract_date"] = earliest.get("event_date")
        if event.get("notice_published_date") is None:
            event["notice_published_date"] = first.get("notice_published_date")
        event["activity_dates"] = sorted(set(event.get("activity_dates") or []) | {
            row["event_date"] for row in contract_rows if row.get("event_date")
        })
        event["contract_amount"] = _number(first.get("contract_amount"))
        event["contract_ids"].extend(
            str(row["unified_contract_number"]) for row in contract_rows
            if row.get("unified_contract_number") not in event["contract_ids"]
        )
        event["amount"] = event.get("contract_amount") or event.get("award_amount")
        for row in sorted(contract_rows, key=lambda value: value.get("event_date") or date.min):
            share = _number(row.get("participation_share_rate"))
            amount = row.get("contract_amount")
            attributed = None
            if row.get("contract_currency") == "KRW" and amount is not None:
                if share is not None:
                    attributed = _number(Decimal(str(amount)) * Decimal(str(share)) / Decimal("100"))
                elif len(member_numbers) == 1:
                    attributed = _number(amount)
            member_number = str(row["company_number"])
            existing_member = event["members"].get(member_number)
            attributed_at = row.get("event_date")
            if attributed_at is not None and existing_member is not None \
                    and existing_member.get("attributed_at"):
                attributed_at = min(existing_member["attributed_at"], attributed_at)
            contract_activity_dates = list(
                (existing_member or {}).get("contract_activity_dates") or []
            )
            if row.get("event_date") is not None:
                contract_activity_dates.append(row["event_date"])
            event["members"][member_number] = {
                "company_number": str(row["company_number"]),
                "company_name": row.get("company_name"), "share_rate": share,
                "supplier_role_name": row.get("supplier_role_name"),
                "attributed_amount": attributed,
                # Attribute the final confirmed amount to the original contract
                # year so amendments do not move one award event across years.
                "attributed_at": attributed_at,
                "contract_activity_dates": sorted(set(contract_activity_dates)),
            }

    events = list(awards.values())
    target_fields = _business_fields(str(notice.get("notice_name") or ""))
    if "1468" in set(map(str, notice.get("industry_codes") or [])) \
            and "시스템" in str(notice.get("notice_name") or ""):
        target_fields.add("information_system")
    target_projects = _project_types(str(notice.get("notice_name") or ""))
    target_amount = notice.get("estimated_price") or notice.get("allocated_budget")
    as_of = notice.get("as_of")
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of or date.today()
    period_start = _fiscal_period_start(as_of_date, period_years)

    def is_field_event(event: dict[str, Any]) -> bool:
        return bool(notice.get("include_all_fields")) or bool(
            target_fields & _business_fields(str(event.get("notice_name") or ""))
        )

    field_events = [event for event in events if is_field_event(event)]
    # A merged award event can have later confirmed-contract or amendment
    # activity. Keep it in the requested operating-period population when any
    # preserved activity falls in the window, while retaining the earliest
    # award date for relationship history and first-award reporting.
    recent_events = [
        event for event in field_events
        if any(
            period_start <= activity_date < as_of_date
            for activity_date in event.get("activity_dates") or []
        )
    ]
    companies: dict[str, dict[str, Any]] = {}
    for event in field_events:
        event_projects = set(event["project_types"])
        is_same_project = bool(target_projects & event_projects)
        is_similar_amount = _amount_similarity(target_amount, event.get("amount"))[0] >= 0.5
        for company_number, member in event["members"].items():
            company = companies.setdefault(company_number, {
                "company_number": company_number, "company_name": member.get("company_name"),
                "events": [], "attributed_contract_amount": Decimal("0"),
                "contract_amount_complete": True,
            })
            if member.get("company_name"):
                company["company_name"] = member["company_name"]
            company["events"].append((event, is_same_project, is_similar_amount))
            if "contract" in event["source_kinds"]:
                if member.get("attributed_amount") is None:
                    company["contract_amount_complete"] = False
                else:
                    company["attributed_contract_amount"] += Decimal(str(member["attributed_amount"]))

    company_metrics: dict[str, dict[str, Any]] = {}
    for company_number, company in companies.items():
        ordered = sorted(company["events"], key=lambda item: item[0].get("awarded_at") or date.min)
        recent = [item for item in ordered if item[0] in recent_events]
        activity_dates = [
            activity_date for event, _, _ in recent
            for activity_date in event.get("activity_dates") or []
            if period_start <= activity_date < as_of_date
        ]
        years = sorted({activity_date.year for activity_date in activity_dates})
        consecutive = 0
        if years:
            expected = years[-1]
            for year in reversed(years):
                if year != expected:
                    break
                consecutive += 1
                expected -= 1
        representatives = sorted(
            recent,
            key=lambda item: (
                int(item[1]) + int(item[2]), int(item[1]), int(item[2]),
                item[0].get("awarded_at") or date.min,
            ), reverse=True,
        )[:3]
        annual: dict[int, dict[str, Any]] = {}
        for event, _, _ in recent:
            member = event["members"][company_number]
            contract_dates = [
                value for value in member.get("contract_activity_dates") or []
                if period_start <= value < as_of_date
            ]
            annualized_at = (
                max(contract_dates) if contract_dates else event.get("awarded_at")
            )
            if annualized_at is None:
                continue
            member_count = len(event["members"])
            year_item = annual.setdefault(annualized_at.year, {
                "year": annualized_at.year,
                "award_event_count": 0,
                "attributed_contract_amount": Decimal("0"),
                "known_amount_count": 0,
                "sole_count": 0,
                "consortium_lead_count": 0,
                "consortium_member_count": 0,
            })
            year_item["award_event_count"] += 1
            attributed_amount = member.get("attributed_amount")
            if attributed_amount is not None:
                year_item["attributed_contract_amount"] += Decimal(str(attributed_amount))
                year_item["known_amount_count"] += 1
            if member_count == 1:
                year_item["sole_count"] += 1
            elif member.get("supplier_role_name") in {"대표사", "주계약자", "대표업체"}:
                year_item["consortium_lead_count"] += 1
            else:
                year_item["consortium_member_count"] += 1

        annual_activity = []
        for year in sorted(annual):
            year_item = annual[year]
            known_count = year_item.pop("known_amount_count")
            event_count = year_item["award_event_count"]
            annual_activity.append({
                **year_item,
                "attributed_contract_amount": _number(
                    year_item["attributed_contract_amount"]
                ),
                "amount_completeness": (
                    "complete" if known_count == event_count
                    else "unknown" if known_count == 0
                    else "partial"
                ),
            })
        company_metrics[company_number] = {
            "same_field_event_count": len(recent),
            "same_project_type_event_count": sum(1 for _, same, _ in recent if same),
            "similar_amount_event_count": sum(1 for _, _, similar in recent if similar),
            "first_award_date": min(activity_dates) if activity_dates else None,
            "latest_award_date": max(activity_dates) if activity_dates else None,
            "active_years": years,
            "active_year_count": len(years),
            "consecutive_active_years": consecutive,
            "annual_activity": annual_activity,
            "same_field_contract_amount": _number(company["attributed_contract_amount"]),
            "same_field_contract_amount_complete": company["contract_amount_complete"],
            "representative_notices": [{
                "notice_id": event.get("notice_id"), "notice_name": event.get("notice_name"),
                "awarded_at": event.get("awarded_at"), "amount": event.get("amount"),
                "project_type": sorted(event["project_types"])[0] if event["project_types"] else None,
                "is_similar_amount": similar,
            } for event, _, similar in representatives],
        }

    recent_company_events: dict[str, list[dict[str, Any]]] = {}
    credit_by_company: dict[str, Decimal] = {}
    unknown_share_event_count = 0
    for event in recent_events:
        members = list(event["members"].values())
        known_shares = [member.get("share_rate") for member in members]
        use_shares = bool(members) and all(share is not None for share in known_shares)
        if len(members) > 1 and not use_shares:
            unknown_share_event_count += 1
        share_total = sum((Decimal(str(value)) for value in known_shares if value is not None), Decimal("0"))
        for member in members:
            number = member["company_number"]
            recent_company_events.setdefault(number, []).append(event)
            credit = (
                Decimal(str(member["share_rate"])) / share_total
                if use_shares and share_total else Decimal("1") / Decimal(str(len(members)))
            )
            credit_by_company[number] = credit_by_company.get(number, Decimal("0")) + credit
    counts = sorted((len(value) for value in recent_company_events.values()), reverse=True)
    total = len(recent_events)
    ranked_credits = sorted(
        credit_by_company.items(), key=lambda item: (-item[1], item[0])
    )
    top_companies = []
    for rank, (company_number, credit) in enumerate(ranked_credits, start=1):
        share = round(float(credit / total), 9) if total else None
        metrics = company_metrics[company_number]
        metrics.update({
            "attributed_award_event_count": _number(credit),
            "market_share": share,
            "market_share_rank": rank,
        })
        top_companies.append({
            "company_number": company_number,
            "company_name": companies[company_number].get("company_name"),
            "attributed_award_event_count": _number(credit),
            "market_share": share,
            "rank": rank,
        })
    def top_share(size: int) -> float | None:
        if not total:
            return None
        return round(sum(item["market_share"] for item in top_companies[:size]), 9)

    distribution = {
        "one": sum(value == 1 for value in counts),
        "two_to_three": sum(2 <= value <= 3 for value in counts),
        "four_to_nine": sum(4 <= value <= 9 for value in counts),
        "ten_or_more": sum(value >= 10 for value in counts),
    }
    recent_year_floor = as_of_date.year - 2
    recent_years = []
    entrant_items = []
    first_event_by_company = {
        number: min(values, key=lambda event: event.get("awarded_at") or date.max)
        for number, values in ((number, [item[0] for item in company["events"]])
                               for number, company in companies.items())
    }
    for year in range(recent_year_floor, as_of_date.year + 1):
        year_events = [event for event in field_events if event.get("awarded_at") and event["awarded_at"].year == year]
        new_events = []
        new_companies = set()
        for event in year_events:
            event_new = False
            for number in event["members"]:
                if first_event_by_company.get(number) is event:
                    new_companies.add(number)
                    event_new = True
                    if not any(item["company_number"] == number for item in entrant_items):
                        entrant_items.append({
                            "company_number": number,
                            "company_name": companies[number].get("company_name"),
                            "first_award_date": event.get("awarded_at"),
                            "representative_notice_id": event.get("notice_id"),
                            "classification": "first_observed",
                        })
            if event_new:
                new_events.append(event)
        recent_years.append({
            "year": year,
            "incumbent_award_count": len(year_events) - len(new_events),
            "new_entrant_award_count": len(new_events),
            "new_entrant_company_count": len(new_companies),
        })

    observation_dates = [event["awarded_at"] for event in events if event.get("awarded_at")]
    missing_reasons = []
    if not recent_events:
        missing_reasons.append("no_matching_award_events")
    if unattributed_contract_count:
        missing_reasons.append("ambiguous_contract_to_award_attribution")
    if unknown_share_event_count:
        missing_reasons.append("joint_supplier_share_missing_equal_split_applied")
    return {
        "all_events": events,
        "events": recent_events,
        "company_metrics": company_metrics,
        "event_deduplication": {
            "award_row_count": sum(row.get("source_kind") == "award" for row in rows),
            "contract_row_count": len(contracts),
            "merged_award_contract_count": len(merged_award_keys),
            "contract_only_event_count": contract_only_count,
            "award_event_count": len(recent_events),
            "unattributed_contract_count": unattributed_contract_count,
        },
        "market_structure": {
            "award_event_count": total,
            "company_count": len(recent_company_events),
            "repeat_company_count": sum(value >= 2 for value in counts),
            "single_award_company_count": sum(value == 1 for value in counts),
            "similar_amount_company_count": sum(
                metrics["similar_amount_event_count"] > 0 for metrics in company_metrics.values()
            ),
            "top_1_share": top_share(1), "top_3_share": top_share(3),
            "top_5_share": top_share(5), "company_distribution": distribution,
            "top_companies": top_companies[:5],
            "market_share_completeness": (
                "partial" if unknown_share_event_count else "complete"
            ),
            "unknown_share_event_count": unknown_share_event_count,
            "unknown_share_policy": "equal_split",
            "validation": {
                "attributed_event_count_sum": _number(sum(credit_by_company.values(), Decimal("0"))),
                "market_share_sum": round(sum(
                    item["market_share"] for item in top_companies
                ), 9),
                "award_event_count": total,
                "balanced": abs(
                    sum(credit_by_company.values(), Decimal("0")) - Decimal(str(total))
                ) <= Decimal("0.000000001"),
            },
            "joint_award_policy": {
                "event_counting": "one_event_per_award",
                "company_presence": "full_presence",
                "market_share_attribution": "confirmed_share_else_equal_split",
                "unknown_share_event_count": unknown_share_event_count,
            },
        },
        "market_entry": {
            "definition": "first_observed_organization_field_award",
            "classification": "first_observed",
            "observation_started_at": min(observation_dates) if observation_dates else None,
            "recent_new_entrant_count": len(entrant_items),
            "recent_years": recent_years,
            "companies": sorted(entrant_items, key=lambda item: item["first_award_date"], reverse=True),
        },
        "data_completeness": {
            "status": "partial" if missing_reasons else "complete",
            "missing_reasons": missing_reasons,
        },
    }


def _business_fields(value: str) -> set[str]:
    patterns = {
        "information_system": (
            "정보시스템", "플랫폼", "소프트웨어", "전산", "정보화",
            "데이터플랫폼", "데이터시스템", "재해복구시스템", "클라우드",
        ),
        "security": ("정보보호", "보안", "방화벽", "침입방지"),
        "communication": ("정보통신", "통신망", "네트워크"),
    }
    compact = _compact(value)
    fields = {field for field, words in patterns.items() if any(word in compact for word in words)}
    if any(marker in compact for marker in ("리스사선정", "계약은행", "펀드평가사선정")):
        fields.discard("information_system")
    return fields


def _amount_similarity(left: Any, right: Any) -> tuple[float, str | None]:
    left_number, right_number = _number(left), _number(right)
    if not left_number or not right_number:
        return 0.0, "amount_unknown"
    ratio = min(float(left_number), float(right_number)) / max(float(left_number), float(right_number))
    return ratio, None if ratio >= 0.5 else "different_amount_range"


def _similar_notice_item(notice: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    trigram = float(row.get("title_trigram_score") or 0)
    token_score = _jaccard(
        _title_tokens(str(notice.get("notice_name") or "")),
        _title_tokens(str(row.get("notice_name") or "")),
    )
    title_score = round(0.7 * trigram + 0.3 * token_score, 4)
    candidate_amount = row.get("estimated_price") or row.get("allocated_budget")
    target_amount = notice.get("estimated_price") or notice.get("allocated_budget")
    target_industries = set(map(str, notice.get("industry_codes") or []))
    candidate_industries = set(map(str, row.get("industry_codes") or []))
    matched_industries = target_industries & candidate_industries
    industry_score = _jaccard(target_industries, candidate_industries)
    target_fields = _business_fields(str(notice.get("notice_name") or ""))
    candidate_fields = _business_fields(str(row.get("notice_name") or ""))
    if "1468" in target_industries and "시스템" in str(notice.get("notice_name") or ""):
        target_fields.add("information_system")
    if "1468" in candidate_industries and "시스템" in str(row.get("notice_name") or ""):
        candidate_fields.add("information_system")
    matched_fields = target_fields & candidate_fields
    target_projects = _project_types(str(notice.get("notice_name") or ""))
    candidate_projects = _project_types(str(row.get("notice_name") or ""))
    matched_projects = target_projects & candidate_projects
    amount_score, amount_difference = _amount_similarity(target_amount, candidate_amount)
    same_organization = bool(
        notice.get("demand_organization_code")
        and notice.get("demand_organization_code") == row.get("demand_organization_code")
    )
    same_contract_method = bool(
        notice.get("contract_method_name") and row.get("contract_method_name")
        and notice.get("contract_method_name") == row.get("contract_method_name")
    )
    published = row.get("notice_published_date")
    as_of = notice.get("as_of")
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    age_years = max(0.0, (as_of_date - published).days / 365.25) if as_of_date and published else 5.0
    recency_score = max(0.0, 1.0 - age_years / 5.0)
    field_score = _jaccard(target_fields, candidate_fields)
    project_score = _jaccard(target_projects, candidate_projects)
    comparison_score = round(
        0.10 + 0.20 * industry_score + 0.25 * field_score + 0.15 * project_score
        + 0.10 * amount_score + 0.05 * float(same_contract_method)
        + 0.10 * title_score + 0.05 * recency_score,
        4,
    )
    broad_license_only = matched_industries == {"1468"} and not matched_fields
    comparison_eligible = bool(
        matched_fields and matched_projects
        and (len(matched_industries) >= 2 or (matched_industries and title_score >= 0.40))
        and not broad_license_only and comparison_score >= 0.55
    )
    price_reference_eligible = bool(
        comparison_eligible and amount_score >= 0.5 and project_score > 0
    )
    organization_field = bool(
        same_organization and (matched_fields or (matched_industries and not broad_license_only))
    )
    relationship_type = (
        "comparable" if comparison_eligible else
        "same_organization_field" if organization_field else
        "title_search_result" if title_score >= 0.40 else None
    )
    matched_factors = ["same_work_type"]
    if same_organization:
        matched_factors.append("same_organization")
    matched_factors.extend(f"industry_license_{code}" for code in sorted(matched_industries))
    matched_factors.extend(sorted(matched_fields))
    matched_factors.extend(f"same_project_type_{kind}" for kind in sorted(matched_projects))
    if same_contract_method:
        matched_factors.append("same_contract_method")
    if amount_score >= 0.5:
        matched_factors.append("similar_amount_range")
    different_factors: list[str] = []
    if target_projects and candidate_projects and not matched_projects:
        different_factors.append(
            f"{'_'.join(sorted(target_projects))}_vs_{'_'.join(sorted(candidate_projects))}"
        )
    elif target_projects and not candidate_projects:
        different_factors.append("project_type_unknown")
    if amount_difference:
        different_factors.append(amount_difference)
    if notice.get("contract_method_name") and row.get("contract_method_name") and not same_contract_method:
        different_factors.append("different_contract_method")
    quality = (
        "strong" if comparison_eligible and comparison_score >= 0.70 else
        "limited" if relationship_type in {"comparable", "same_organization_field"} else
        "reference_only"
    )
    return {
        "bid_notice_id": row["bid_notice_id"], "notice_name": row["notice_name"],
        "notice_published_date": row.get("notice_published_date"),
        "organization_code": row.get("demand_organization_code"),
        "organization_name": row.get("demand_organization_name"),
        "work_type": row.get("work_type"), "estimated_price": _number(candidate_amount),
        "winning_company_number": row.get("winner_business_registration_number"),
        "winning_company_name": row.get("winner_name"),
        "winning_amount": _number(row.get("winning_amount")),
        "winning_rate": _number(row.get("winning_rate")), "award_date": row.get("award_date"),
        "similarity_score": title_score,
        "similarity_level": "high" if title_score >= 0.75 else "medium" if title_score >= 0.55 else "low",
        "similarity_reasons": ["notice_title_similar"] if title_score >= 0.40 else [],
        "relationship_type": relationship_type,
        "comparison_score": comparison_score,
        "comparison_quality": quality,
        "comparison_eligible": comparison_eligible,
        "price_reference_eligible": price_reference_eligible,
        "matched_factors": matched_factors,
        "different_factors": different_factors,
        "matched_features": {
            "title_score": title_score,
            "title_trigram_score": round(trigram, 4),
            "title_token_score": round(token_score, 4),
           "work_type": True,
            "industry_score": round(industry_score, 4),
            "field_score": round(field_score, 4),
            "project_type_score": round(project_score, 4),
            "amount_score": round(amount_score, 4),
            "same_organization": same_organization,
            "same_contract_method": same_contract_method,
        },
    }


_SIMILAR_NOTICE_CANDIDATES_QUERY = """
WITH target AS (
    SELECT public_procurement.normalize_bid_notice_title(notice_name) AS normalized_title
    FROM public_procurement.bid_notices
    WHERE notice_number=%(notice_number)s AND notice_order=%(notice_order)s
), title_candidates AS MATERIALIZED (
    SELECT n.notice_number, n.notice_order
    FROM public_procurement.bid_notices n
    CROSS JOIN target t
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=%(work_type)s
      AND n.notice_published_at >= date_trunc('year', %(as_of)s::timestamptz)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < %(as_of)s::timestamptz
      AND public_procurement.normalize_bid_notice_title(n.notice_name) %% t.normalized_title
    ORDER BY public_procurement.normalize_bid_notice_title(n.notice_name) <-> t.normalized_title
    LIMIT %(candidate_limit)s
), organization_candidates AS MATERIALIZED (
    SELECT n.notice_number, n.notice_order
    FROM public_procurement.bid_notices n
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=%(work_type)s
      AND n.demand_organization_code=%(organization_code)s
      AND n.notice_published_at >= date_trunc('year', %(as_of)s::timestamptz)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < %(as_of)s::timestamptz
    ORDER BY n.notice_published_at DESC
    LIMIT %(candidate_limit)s
), candidate_notices AS (
    SELECT * FROM title_candidates
    UNION
    SELECT * FROM organization_candidates
)
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_number, n.notice_order, n.notice_name, n.work_type,
       n.notice_published_at::date AS notice_published_date,
       n.contract_method_name, n.estimated_price, n.allocated_budget,
       n.demand_organization_code, n.demand_organization_name,
       licenses.industry_codes,
       similarity(public_procurement.normalize_bid_notice_title(a.notice_name),
                  t.normalized_title) AS title_trigram_score,
       a.winner_business_registration_number, a.winner_name,
       a.winning_amount, a.winning_rate,
       COALESCE(a.final_award_date, a.opening_at::date) AS award_date
FROM candidate_notices candidate
JOIN public_procurement.bid_notices n USING (notice_number, notice_order)
JOIN public_procurement.bid_awards a USING (notice_number, notice_order)
CROSS JOIN target t
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
           AS industry_codes
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
      AND l.license_restriction_name ~ '/[0-9]{4}$'
) licenses ON true
WHERE a.work_type=%(work_type)s
  AND a.opening_at >= date_trunc('year', %(as_of)s::timestamptz)
      - ((%(period_years)s - 1) * interval '1 year')
  AND a.opening_at < %(as_of)s::timestamptz
  AND (
    %(include_awarded)s OR (
      %(include_contracted)s AND EXISTS (
        SELECT 1 FROM public_procurement.contracts c
        WHERE c.notice_number=a.notice_number
      )
    )
  )
ORDER BY (n.demand_organization_code=%(organization_code)s) DESC,
         similarity(public_procurement.normalize_bid_notice_title(a.notice_name),
                    t.normalized_title) DESC
LIMIT %(candidate_limit)s
"""

_COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY = """
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_name, n.work_type, n.estimated_price, n.allocated_budget,
       LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
       COALESCE(licenses.industry_codes,ARRAY[]::text[]) AS industry_codes,
       COALESCE(licenses.industry_names,'{}'::jsonb) AS industry_names
FROM public_procurement.bid_notices n
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
             FILTER (WHERE l.license_restriction_name ~ '/[0-9]{4}$') AS industry_codes,
           jsonb_object_agg(
               substring(l.license_restriction_name FROM '/([0-9]{4})$'),
               regexp_replace(l.license_restriction_name,'/[0-9]{4}$','')
           ) FILTER (WHERE l.license_restriction_name ~ '/[0-9]{4}$') AS industry_names
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
) licenses ON true
WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
"""

_COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY = """
WITH reference AS (
    SELECT n.work_type,LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
           public_procurement.normalize_bid_notice_title(n.notice_name) AS normalized_title,
           ARRAY(
               SELECT DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
               FROM public_procurement.bid_notice_license_restrictions l
               WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
                 AND l.license_restriction_name ~ '/[0-9]{4}$'
           )::text[] AS industry_codes
    FROM public_procurement.bid_notices n
    WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
), company_awards AS MATERIALIZED (
    SELECT DISTINCT ON (a.notice_number,a.notice_order)
           a.notice_number,a.notice_order,
           COALESCE(a.final_award_date,a.opening_at::date) AS award_date,
           a.winning_amount
    FROM public_procurement.bid_awards a
    WHERE a.winner_business_registration_number=%(company_number)s
    ORDER BY a.notice_number,a.notice_order,
             COALESCE(a.final_award_date,a.opening_at::date) DESC NULLS LAST
), company_contracts AS MATERIALIZED (
    SELECT DISTINCT ON (normalized_notice_number)
           normalized_notice_number,c.concluded_date AS contract_date,
           c.current_contract_amount AS contract_amount,
           cs.participation_share_rate,cs.supplier_role_name,
           (SELECT count(*) FROM public_procurement.contract_suppliers all_cs
            WHERE all_cs.unified_contract_number=c.unified_contract_number) AS supplier_count
    FROM public_procurement.contract_suppliers cs
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN LATERAL (
        SELECT CASE
          WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
            THEN left(c.notice_number,length(c.notice_number)-2)
          ELSE c.notice_number
        END AS normalized_notice_number
    ) normalized
    WHERE cs.business_registration_number=%(company_number)s
      AND COALESCE(c.notice_number,'')<>''
    ORDER BY normalized_notice_number,c.concluded_date DESC NULLS LAST
), company_notice_keys AS MATERIALIZED (
    SELECT notice_number,notice_order FROM company_awards
    UNION
    SELECT normalized_notice_number,'000'::text FROM company_contracts
), candidates AS MATERIALIZED (
    SELECT n.*
    FROM company_notice_keys k
    JOIN public_procurement.bid_notices n
      ON n.notice_number=k.notice_number AND n.notice_order=k.notice_order
    CROSS JOIN reference r
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=r.work_type
      AND n.notice_published_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < r.as_of
      AND EXISTS (
          SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
          WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
            AND l.license_restriction_name ~ '/[0-9]{4}$'
            AND substring(l.license_restriction_name FROM '/([0-9]{4})$')=ANY(r.industry_codes)
      )
)
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_name, n.notice_published_at::date AS notice_published_date,
       n.work_type, n.estimated_price, n.allocated_budget,
       n.demand_organization_code, n.demand_organization_name,
       licenses.industry_codes,
       award.award_date, award.winning_amount,
       contract.contract_date, contract.contract_amount,
       contract.participation_share_rate, contract.supplier_role_name,
       contract.supplier_count,
       similarity(public_procurement.normalize_bid_notice_title(n.notice_name),
                  r.normalized_title) AS title_trigram_score
FROM candidates n
CROSS JOIN reference r
LEFT JOIN company_awards award USING (notice_number,notice_order)
LEFT JOIN company_contracts contract
  ON contract.normalized_notice_number=n.notice_number
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
           AS industry_codes
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
      AND l.license_restriction_name ~ '/[0-9]{4}$'
) licenses ON true
WHERE award.award_date IS NOT NULL OR contract.contract_date IS NOT NULL
ORDER BY COALESCE(contract.contract_date,award.award_date,n.notice_published_at::date) DESC
"""

_COMPANY_SIMILAR_PROJECT_METRICS_QUERY = """
WITH reference AS (
    SELECT n.notice_name AS reference_notice_name,n.work_type,
           LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
           COALESCE(n.estimated_price,n.allocated_budget)::numeric AS reference_amount,
           ARRAY(
               SELECT DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
               FROM public_procurement.bid_notice_license_restrictions l
               WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
                 AND l.license_restriction_name ~ '/[0-9]{4}$'
           )::text[] AS industry_codes
    FROM public_procurement.bid_notices n
    WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
), company_awards AS MATERIALIZED (
    SELECT DISTINCT ON (a.winner_business_registration_number,a.notice_number,a.notice_order)
           a.winner_business_registration_number AS company_number,
           a.notice_number,a.notice_order,a.winning_amount
    FROM public_procurement.bid_awards a
    CROSS JOIN reference r
    WHERE a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.work_type=r.work_type
      AND a.opening_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND a.opening_at < r.as_of
    ORDER BY a.winner_business_registration_number,a.notice_number,a.notice_order,
             COALESCE(a.final_award_date,a.opening_at::date) DESC NULLS LAST
), company_contracts AS MATERIALIZED (
    SELECT DISTINCT ON (cs.business_registration_number,normalized_notice_number)
           cs.business_registration_number AS company_number,
           normalized_notice_number,c.current_contract_amount AS contract_amount
    FROM public_procurement.contract_suppliers cs
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN reference r
    CROSS JOIN LATERAL (
        SELECT CASE
          WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
            THEN left(c.notice_number,length(c.notice_number)-2)
          ELSE c.notice_number
        END AS normalized_notice_number
    ) normalized
    WHERE cs.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(c.notice_number,'')<>''
      AND c.contract_type=r.work_type
      AND c.concluded_date >= (
          date_trunc('year', r.as_of) - ((%(period_years)s - 1) * interval '1 year')
      )::date
      AND c.concluded_date < r.as_of::date
    ORDER BY cs.business_registration_number,normalized_notice_number,
             c.concluded_date DESC NULLS LAST
), company_notice_keys AS (
    SELECT company_number,notice_number,notice_order FROM company_awards
    UNION
    SELECT company_number,normalized_notice_number,'000'::text FROM company_contracts
), eligible_events AS (
    SELECT k.company_number,n.notice_number,n.notice_order,n.notice_name,
           r.reference_notice_name,
           COALESCE(c.contract_amount,a.winning_amount,n.estimated_price,n.allocated_budget)::numeric
             AS event_amount,r.reference_amount
    FROM company_notice_keys k
    JOIN public_procurement.bid_notices n
      ON n.notice_number=k.notice_number AND n.notice_order=k.notice_order
    CROSS JOIN reference r
    LEFT JOIN company_awards a
      ON a.company_number=k.company_number AND a.notice_number=n.notice_number
     AND a.notice_order=n.notice_order
    LEFT JOIN company_contracts c
      ON c.company_number=k.company_number AND c.normalized_notice_number=n.notice_number
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=r.work_type
      AND n.notice_published_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < r.as_of
      AND EXISTS (
          SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
          WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
            AND l.license_restriction_name ~ '/[0-9]{4}$'
            AND substring(l.license_restriction_name FROM '/([0-9]{4})$')=ANY(r.industry_codes)
      )
)
, scored AS (
    SELECT company_number,
           similarity(
               public_procurement.normalize_bid_notice_title(notice_name),
               public_procurement.normalize_bid_notice_title(reference_notice_name)
           ) >= 0.08 AS title_related,
           (
             (reference_notice_name~'(구축|개발|도입)' AND notice_name~'(구축|개발|도입)') OR
             (reference_notice_name~'(개선|고도화|재구축)' AND notice_name~'(개선|고도화|재구축)') OR
             (reference_notice_name~'(유지보수|유지관리|운영)' AND notice_name~'(유지보수|유지관리|운영)') OR
             (reference_notice_name~'(컨설팅|감리|설계)' AND notice_name~'(컨설팅|감리|설계)')
           ) AS project_type_match,
           CASE WHEN reference_amount IS NOT NULL AND reference_amount>0
                  AND event_amount IS NOT NULL AND event_amount>0
                THEN least(reference_amount,event_amount)/greatest(reference_amount,event_amount)>=0.5
                ELSE false END AS is_similar_amount
    FROM eligible_events
)
SELECT company_number,count(*) AS candidate_count,
       count(*) FILTER (WHERE title_related OR project_type_match) AS event_count,
       count(*) FILTER (WHERE title_related AND project_type_match) AS strong_event_count,
       count(*) FILTER (WHERE title_related<>project_type_match) AS limited_event_count,
       count(*) FILTER (WHERE NOT title_related AND NOT project_type_match)
         AS reference_only_event_count,
       count(*) FILTER (
           WHERE (title_related OR project_type_match) AND is_similar_amount
       ) AS similar_amount_event_count
FROM scored
GROUP BY company_number
"""

_RELEVANT_COMPANY_ACTIVITIES_QUERY = """
WITH similar_notices AS (
    SELECT * FROM jsonb_to_recordset(%(similar_notices)s::jsonb)
      AS n(bid_notice_id text, notice_number text, notice_order text)
), participation_activities AS (
    SELECT bp.business_registration_number AS company_number,
           sn.bid_notice_id, bp.bid_classification_number, bp.rebid_number,
           bp.opening_rank, bp.bid_amount,
           a.winning_amount,
           CASE WHEN a.award_id IS NULL THEN 'participation_only'
                WHEN a.winner_business_registration_number=bp.business_registration_number
                THEN 'awarded' ELSE 'not_awarded' END AS result,
           COALESCE(bp.bid_at, a.opening_at, bp.created_at)::date AS activity_date,
           NULL::text AS unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.bid_opening_participants bp
      ON bp.notice_number=sn.notice_number AND bp.notice_order=sn.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE bp.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(bp.bid_at, a.opening_at, bp.created_at) < %(as_of)s
), award_only_activities AS (
    SELECT a.winner_business_registration_number AS company_number,
           sn.bid_notice_id, a.bid_classification_number, a.rebid_number,
           NULL::integer AS opening_rank, a.winning_amount AS bid_amount, a.winning_amount,
           'awarded'::text AS result,
           COALESCE(a.final_award_date, a.opening_at::date) AS activity_date,
           NULL::text AS unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.bid_awards a
      ON a.notice_number=sn.notice_number AND a.notice_order=sn.notice_order
    WHERE a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.opening_at < %(as_of)s
      AND NOT EXISTS (
        SELECT 1 FROM public_procurement.bid_opening_participants bp
        WHERE bp.notice_number=a.notice_number AND bp.notice_order=a.notice_order
          AND bp.bid_classification_number=a.bid_classification_number
          AND bp.rebid_number=a.rebid_number
          AND bp.business_registration_number=a.winner_business_registration_number
      )
), contract_activities AS (
    SELECT DISTINCT cs.business_registration_number AS company_number,
           sn.bid_notice_id, NULL::text AS bid_classification_number,
           NULL::text AS rebid_number, NULL::integer AS opening_rank,
           NULL::numeric AS bid_amount, NULL::numeric AS winning_amount,
           'contracted'::text AS result, c.concluded_date AS activity_date,
           c.unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.contracts c ON c.notice_number=sn.notice_number
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE cs.business_registration_number=ANY(%(company_numbers)s)
      AND c.concluded_date < %(as_of)s::date
)
SELECT * FROM participation_activities
UNION ALL SELECT * FROM award_only_activities
UNION ALL SELECT * FROM contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
"""


_ORGANIZATION_RELATIONSHIP_ACTIVITIES_QUERY = """
WITH participation_activities AS (
    SELECT bp.business_registration_number AS company_number,
           bp.notice_number || ':' || bp.notice_order AS bid_notice_id,
           n.notice_name, n.notice_published_at::date AS notice_published_date,
           bp.bid_classification_number, bp.rebid_number,
           bp.opening_rank, bp.bid_amount,
           CASE WHEN a.award_id IS NULL THEN 'participation_only'
                WHEN a.winner_business_registration_number=bp.business_registration_number
                THEN 'awarded' ELSE 'not_awarded' END AS result,
           COALESCE(bp.bid_at, a.opening_at, bp.created_at)::date AS activity_date,
           NULL::text AS unified_contract_number
    FROM public_procurement.bid_opening_participants bp
    JOIN public_procurement.bid_notices n
      ON n.notice_number=bp.notice_number AND n.notice_order=bp.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE n.demand_organization_code=%(organization_code)s
      AND bp.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(bp.bid_at, a.opening_at, bp.created_at) < %(as_of)s
), award_only_activities AS (
    SELECT a.winner_business_registration_number AS company_number,
           a.notice_number || ':' || a.notice_order AS bid_notice_id,
           n.notice_name, n.notice_published_at::date AS notice_published_date,
           a.bid_classification_number, a.rebid_number,
           NULL::integer AS opening_rank, a.winning_amount AS bid_amount,
           'awarded'::text AS result,
           COALESCE(a.final_award_date, a.opening_at::date) AS activity_date,
           NULL::text AS unified_contract_number
    FROM public_procurement.bid_awards a
    JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE n.demand_organization_code=%(organization_code)s
      AND a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.opening_at < %(as_of)s
      AND NOT EXISTS (
        SELECT 1 FROM public_procurement.bid_opening_participants bp
        WHERE bp.notice_number=a.notice_number AND bp.notice_order=a.notice_order
          AND bp.bid_classification_number=a.bid_classification_number
          AND bp.rebid_number=a.rebid_number
          AND bp.business_registration_number=a.winner_business_registration_number
      )
), organization_contract_activities AS (
    SELECT cs.business_registration_number AS company_number,
           CASE WHEN COALESCE(c.notice_number,'')<>''
                THEN c.notice_number || ':000'
                ELSE 'contract:' || COALESCE(NULLIF(c.confirmed_contract_number,''),
                                              c.unified_contract_number) END AS bid_notice_id,
           c.contract_name AS notice_name, c.concluded_date AS notice_published_date,
           NULL::text AS bid_classification_number, NULL::text AS rebid_number,
           NULL::integer AS opening_rank,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS bid_amount,
           'contracted'::text AS result, c.concluded_date AS activity_date,
           c.unified_contract_number
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND cs.business_registration_number=ANY(%(company_numbers)s)
      AND c.concluded_date < %(as_of)s::date
)
SELECT * FROM participation_activities
UNION ALL SELECT * FROM award_only_activities
UNION ALL SELECT * FROM organization_contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
"""

_PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY = """
SELECT requested.procurement_classification_number,
       hierarchy.procurement_large_classification_name,
       hierarchy.procurement_middle_classification_name,
       hierarchy.purchase_items
FROM unnest(%(classification_numbers)s::text[])
  AS requested(procurement_classification_number)
CROSS JOIN LATERAL (
    SELECT n.procurement_large_classification_name,
           n.procurement_middle_classification_name,n.purchase_items
    FROM public_procurement.bid_notices n
    WHERE n.procurement_classification_number=requested.procurement_classification_number
      AND (n.procurement_large_classification_name IS NOT NULL
           OR n.procurement_middle_classification_name IS NOT NULL)
    ORDER BY n.notice_published_at DESC
    LIMIT 1
) hierarchy
"""


_PROCUREMENT_PROFILE_ACTIVITIES_QUERY = """
WITH participation AS (
    SELECT 'participation'::text AS activity_type,
           bp.notice_number||':'||bp.notice_order AS event_key,
           bp.notice_number||':'||bp.notice_order AS bid_notice_id,
           n.notice_name,n.demand_organization_code AS organization_code,
           n.demand_organization_name AS organization_name,
           n.procurement_classification_number,n.procurement_classification_name,
           n.procurement_large_classification_name,
           n.procurement_middle_classification_name,
           n.purchase_items,
           n.work_type,
           bp.business_registration_number AS company_number,bp.participant_name AS company_name,
           COALESCE(bp.bid_at,a.opening_at,bp.created_at)::date AS activity_date,
           bp.bid_amount AS event_amount,NULL::numeric AS attributed_contract_amount,
           'unknown'::text AS amount_completeness
    FROM public_procurement.bid_opening_participants bp
    JOIN public_procurement.bid_notices n
      ON n.notice_number=bp.notice_number AND n.notice_order=bp.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE (%(organization_code)s::text IS NULL OR n.demand_organization_code=%(organization_code)s)
      AND (cardinality(%(company_numbers)s::text[])=0
           OR bp.business_registration_number=ANY(%(company_numbers)s::text[]))
      AND COALESCE(bp.bid_at,a.opening_at,bp.created_at)::date >= %(period_from)s
      AND COALESCE(bp.bid_at,a.opening_at,bp.created_at)::date < %(period_to)s
), awards AS (
    SELECT 'award'::text AS activity_type,
           concat_ws(':',a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number)
             AS event_key,
           a.notice_number||':'||a.notice_order AS bid_notice_id,
           COALESCE(n.notice_name,a.notice_name) AS notice_name,
           a.demand_organization_code AS organization_code,
           a.demand_organization_name AS organization_name,
           n.procurement_classification_number,n.procurement_classification_name,
           n.procurement_large_classification_name,
           n.procurement_middle_classification_name,
           n.purchase_items,
           n.work_type,
           a.winner_business_registration_number AS company_number,a.winner_name AS company_name,
           COALESCE(a.final_award_date,a.opening_at::date) AS activity_date,
           a.winning_amount AS event_amount,NULL::numeric AS attributed_contract_amount,
           'unknown'::text AS amount_completeness
    FROM public_procurement.bid_awards a
    LEFT JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE (%(organization_code)s::text IS NULL OR a.demand_organization_code=%(organization_code)s)
      AND (cardinality(%(company_numbers)s::text[])=0
           OR a.winner_business_registration_number=ANY(%(company_numbers)s::text[]))
      AND COALESCE(a.final_award_date,a.opening_at::date) >= %(period_from)s
      AND COALESCE(a.final_award_date,a.opening_at::date) < %(period_to)s
), latest_contracts AS (
    SELECT DISTINCT ON (
             d.organization_code,cs.business_registration_number,
             COALESCE(NULLIF(c.confirmed_contract_number,''),
                      NULLIF(c.contract_reference_number,''),c.unified_contract_number)
           )
           'contract'::text AS activity_type,
           COALESCE(NULLIF(c.confirmed_contract_number,''),
                    NULLIF(c.contract_reference_number,''),c.unified_contract_number) AS event_key,
           CASE WHEN COALESCE(c.notice_number,'')<>''
                THEN (CASE WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
                           THEN left(c.notice_number,length(c.notice_number)-2)
                           ELSE c.notice_number END)||':000'
                ELSE 'contract:'||c.unified_contract_number END AS bid_notice_id,
           c.contract_name AS notice_name,d.organization_code,o.organization_name,
           c.procurement_classification_number,c.procurement_classification_name,
           NULL::text AS procurement_large_classification_name,
           NULL::text AS procurement_middle_classification_name,
           NULL::jsonb AS purchase_items,
           CASE WHEN c.contract_type='foreign_procurement' THEN 'foreign'
                ELSE c.contract_type END AS work_type,
           cs.business_registration_number AS company_number,cs.supplier_name AS company_name,
           c.concluded_date AS activity_date,c.current_contract_amount AS event_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                  THEN c.current_contract_amount*cs.participation_share_rate/100
                WHEN supplier_count.count=1 THEN c.current_contract_amount END
             AS attributed_contract_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN 'unknown'
                WHEN cs.participation_share_rate IS NOT NULL OR supplier_count.count=1
                  THEN 'complete' ELSE 'partial' END AS amount_completeness
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    LEFT JOIN public_procurement.public_organizations o
      ON o.organization_code=d.organization_code
    CROSS JOIN LATERAL (
      SELECT count(*) FROM public_procurement.contract_suppliers all_cs
      WHERE all_cs.unified_contract_number=c.unified_contract_number
    ) supplier_count
    WHERE (%(organization_code)s::text IS NULL OR d.organization_code=%(organization_code)s)
      AND (cardinality(%(company_numbers)s::text[])=0
           OR cs.business_registration_number=ANY(%(company_numbers)s::text[]))
      AND c.concluded_date >= %(period_from)s AND c.concluded_date < %(period_to)s
    ORDER BY d.organization_code,cs.business_registration_number,
             COALESCE(NULLIF(c.confirmed_contract_number,''),
                      NULLIF(c.contract_reference_number,''),c.unified_contract_number),
             c.concluded_date DESC,c.updated_at DESC
)
SELECT * FROM participation
UNION ALL SELECT * FROM awards
UNION ALL SELECT * FROM latest_contracts
ORDER BY activity_date DESC,activity_type,event_key
"""


_ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY = """
WITH relationship_events AS (
    SELECT cs.business_registration_number AS company_number,
           c.concluded_date AS activity_date
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND cs.business_registration_number IS NOT NULL
      AND c.concluded_date >= %(history_from)s
)
SELECT company_number,min(activity_date) AS first_activity_date
FROM relationship_events
WHERE activity_date IS NOT NULL
GROUP BY company_number
"""

_BID_RELATIONSHIP_NOTICE_QUERY = """
SELECT n.notice_number||':'||n.notice_order AS bid_notice_id,n.notice_name,
       n.demand_organization_code AS organization_code,
       n.demand_organization_name AS organization_name,
       n.notice_published_at::date AS notice_published_date
FROM public_procurement.bid_notices n
WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
"""

_BID_RELATIONSHIP_PARTICIPANTS_QUERY = """
WITH participant_base AS (
    SELECT bp.business_registration_number AS company_number,bp.participant_name AS company_name,
           bp.opening_rank,bp.bid_amount,bp.bid_rate,
           a.final_award_date AS award_date,a.winning_amount,a.winning_rate
    FROM public_procurement.bid_opening_participants bp
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
     AND a.winner_business_registration_number=bp.business_registration_number
    WHERE bp.notice_number=%(notice_number)s AND bp.notice_order=%(notice_order)s
), contract_base AS (
    SELECT DISTINCT ON (cs.business_registration_number)
           cs.business_registration_number AS company_number,cs.supplier_name AS company_name,
           c.concluded_date AS contract_date,c.current_contract_amount AS contract_amount,
           cs.participation_share_rate AS share_percent,cs.supplier_role_name,
           supplier_count.count AS supplier_count,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                  THEN c.current_contract_amount*cs.participation_share_rate/100
                WHEN supplier_count.count=1 THEN c.current_contract_amount END
             AS attributed_contract_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN 'unknown'
                WHEN cs.participation_share_rate IS NOT NULL OR supplier_count.count=1
                  THEN 'complete' ELSE 'partial' END AS amount_completeness
    FROM public_procurement.contracts c
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    CROSS JOIN LATERAL (
      SELECT count(*) FROM public_procurement.contract_suppliers all_cs
      WHERE all_cs.unified_contract_number=c.unified_contract_number
    ) supplier_count
    WHERE c.notice_number IN (
      %(notice_number)s,
      CASE WHEN %(notice_number)s~'^[0-9]+$' THEN %(notice_number)s||'00' ELSE %(notice_number)s END
    )
    ORDER BY cs.business_registration_number,c.concluded_date DESC,c.updated_at DESC
), companies AS (
    SELECT company_number FROM participant_base
    UNION SELECT company_number FROM contract_base
)
SELECT companies.company_number,COALESCE(p.company_name,c.company_name) AS company_name,
       p.opening_rank,p.bid_amount,p.bid_rate,p.award_date,p.winning_amount,p.winning_rate,
       c.contract_date,c.contract_amount,c.attributed_contract_amount,c.share_percent,
       CASE WHEN c.supplier_count=1 THEN 'sole'
            WHEN c.supplier_role_name IN ('대표사','주계약자','대표업체') THEN 'consortium_lead'
            ELSE 'consortium_member' END AS company_role,
       c.amount_completeness
FROM companies
LEFT JOIN participant_base p USING (company_number)
LEFT JOIN contract_base c USING (company_number)
ORDER BY p.opening_rank NULLS LAST,companies.company_number
"""

_ORGANIZATION_AWARD_CONTRACT_ACTIVITIES_QUERY = """
WITH award_activities AS (
    SELECT a.winner_business_registration_number AS company_number,
           a.notice_number || ':' || a.notice_order AS bid_notice_id,
           n.notice_name, n.notice_published_at::date AS notice_published_date,
           a.bid_classification_number, a.rebid_number,
           NULL::integer AS opening_rank, a.winning_amount AS bid_amount,
           'awarded'::text AS result,
           COALESCE(a.final_award_date, a.opening_at::date) AS activity_date,
           NULL::text AS unified_contract_number
    FROM public_procurement.bid_awards a
    JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE n.demand_organization_code=%(organization_code)s
      AND a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.opening_at < %(as_of)s
), contract_activities AS (
    SELECT cs.business_registration_number AS company_number,
           CASE WHEN COALESCE(c.notice_number,'')<>''
                THEN c.notice_number || ':000'
                ELSE 'contract:' || COALESCE(NULLIF(c.confirmed_contract_number,''),
                                              c.unified_contract_number) END AS bid_notice_id,
           c.contract_name AS notice_name, c.concluded_date AS notice_published_date,
           NULL::text AS bid_classification_number, NULL::text AS rebid_number,
           NULL::integer AS opening_rank,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS bid_amount,
           'contracted'::text AS result, c.concluded_date AS activity_date,
           c.unified_contract_number
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND cs.business_registration_number=ANY(%(company_numbers)s)
      AND c.concluded_date < %(as_of)s::date
)
SELECT * FROM award_activities
UNION ALL SELECT * FROM contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
"""


_ORGANIZATION_FIELD_EVENT_ROWS_QUERY = """
WITH organization_awards AS (
    SELECT 'award'::text AS source_kind,
           a.notice_number, a.notice_order, a.bid_classification_number,
           a.rebid_number, NULL::text AS unified_contract_number,
           NULL::text AS original_contract_number,
           a.notice_number || ':' || a.notice_order AS bid_notice_id,
           COALESCE(n.notice_name,a.notice_name) AS notice_name,
           COALESCE(a.final_award_date,a.opening_at::date) AS event_date,
           a.winning_amount AS event_amount,
           a.winner_business_registration_number AS company_number,
           a.winner_name AS company_name,
           NULL::numeric AS participation_share_rate,
           NULL::text AS supplier_role_name,
           n.notice_published_at::date AS notice_published_date,
           NULL::text AS contract_period_text,
           NULL::numeric AS contract_amount,
           NULL::text AS contract_currency
    FROM public_procurement.bid_awards a
    LEFT JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE a.demand_organization_code=%(organization_code)s
      AND (%(work_type)s::text IS NULL OR a.work_type=%(work_type)s)
      AND COALESCE(a.final_award_date,a.opening_at::date)<%(as_of)s::date
      AND a.winner_business_registration_number IS NOT NULL
), organization_contracts AS (
    SELECT 'contract'::text AS source_kind,
           NULLIF(c.notice_number,'') AS notice_number,
           NULL::text AS notice_order, NULL::text AS bid_classification_number,
           NULL::text AS rebid_number, c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''),
                    NULLIF(c.contract_reference_number,''),c.unified_contract_number)
             AS original_contract_number,
           CASE WHEN COALESCE(c.notice_number,'')<>'' THEN c.notice_number || ':000'
                ELSE 'contract:' || c.unified_contract_number END AS bid_notice_id,
           c.contract_name AS notice_name, c.concluded_date AS event_date,
           c.current_contract_amount AS event_amount,
           cs.business_registration_number AS company_number,
           cs.supplier_name AS company_name,
           cs.participation_share_rate, cs.supplier_role_name,
           NULL::date AS notice_published_date,
           c.contract_period_text,
           c.current_contract_amount AS contract_amount,
           COALESCE(c.current_contract_amount_currency,'KRW') AS contract_currency
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND (%(work_type)s::text IS NULL OR c.contract_type=%(work_type)s)
      AND c.concluded_date<%(as_of)s::date
      AND cs.business_registration_number IS NOT NULL
)
SELECT * FROM organization_awards
UNION ALL
SELECT * FROM organization_contracts
ORDER BY event_date,source_kind,notice_number,unified_contract_number,company_number
"""


_RELEVANT_COMPANY_QUERY = """
WITH similar_notices AS (
    SELECT * FROM jsonb_to_recordset(%(similar_notices)s::jsonb)
      AS n(bid_notice_id text, notice_number text, notice_order text)
),
params AS (
    SELECT %(organization_code)s::text AS organization_code,
           %(as_of)s::timestamptz AS as_of
),
similar_participations AS (
    SELECT bp.business_registration_number AS company_number,
           max(bp.participant_name) AS company_name,
           count(DISTINCT bp.bid_notice_id) AS participation_count,
           array_agg(DISTINCT sn.bid_notice_id ORDER BY sn.bid_notice_id) AS notice_ids,
           min(COALESCE(bp.bid_at, bp.created_at)::date) AS first_date,
           max(COALESCE(bp.bid_at, bp.created_at)::date) AS latest_date
    FROM similar_notices sn
    JOIN public_procurement.bid_opening_participants bp
      ON bp.notice_number=sn.notice_number AND bp.notice_order=sn.notice_order
    CROSS JOIN params p
    WHERE COALESCE(bp.bid_at, bp.created_at) < p.as_of
    GROUP BY bp.business_registration_number
),
similar_awards AS (
    SELECT a.winner_business_registration_number AS company_number,
           max(a.winner_name) AS company_name,
           count(DISTINCT a.award_id) AS award_count,
           sum(a.winning_amount) AS award_amount,
           array_agg(DISTINCT sn.bid_notice_id ORDER BY sn.bid_notice_id) AS notice_ids,
           min(a.opening_at::date) AS first_date,
           max(a.opening_at::date) AS latest_date
    FROM similar_notices sn
    JOIN public_procurement.bid_awards a
      ON a.notice_number=sn.notice_number AND a.notice_order=sn.notice_order
    CROSS JOIN params p
    WHERE a.winner_business_registration_number IS NOT NULL
      AND a.opening_at < p.as_of
    GROUP BY a.winner_business_registration_number
),
similar_contract_rows AS (
    SELECT cs.business_registration_number AS company_number,
           cs.supplier_name AS company_name, c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''), c.unified_contract_number)
             AS contract_key,
           sn.bid_notice_id, c.concluded_date,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS attributed_amount
    FROM similar_notices sn
    JOIN public_procurement.contracts c ON c.notice_number=sn.notice_number
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    CROSS JOIN params p
    WHERE cs.business_registration_number IS NOT NULL
      AND c.concluded_date < p.as_of::date
),
similar_contract_records AS (
    SELECT company_number, max(company_name) AS company_name, contract_key,
           bid_notice_id,
           count(DISTINCT unified_contract_number) AS unified_contract_count,
           max(attributed_amount) AS attributed_amount,
           bool_and(attributed_amount IS NOT NULL) AS amount_complete,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM similar_contract_rows
    GROUP BY company_number, contract_key, bid_notice_id
),
similar_contracts AS (
    SELECT company_number, max(company_name) AS company_name,
           count(DISTINCT contract_key) AS contract_count,
           sum(unified_contract_count) AS unified_contract_count,
           sum(attributed_amount) AS contract_amount,
           bool_and(amount_complete) AS amount_complete,
           array_agg(DISTINCT bid_notice_id ORDER BY bid_notice_id) AS notice_ids,
           min(first_date) AS first_date, max(latest_date) AS latest_date
    FROM similar_contract_records GROUP BY company_number
),
organization_awards AS (
    SELECT a.winner_business_registration_number AS company_number,
           max(a.winner_name) AS company_name,
           count(DISTINCT a.award_id) AS award_count,
           min(a.opening_at::date) AS first_date, max(a.opening_at::date) AS latest_date
    FROM public_procurement.bid_awards a, params p
    WHERE a.demand_organization_code=p.organization_code
      AND a.opening_at < p.as_of
      AND a.winner_business_registration_number IS NOT NULL
    GROUP BY a.winner_business_registration_number
),
organization_participations AS (
    SELECT bp.business_registration_number AS company_number,
           max(bp.participant_name) AS company_name,
           count(DISTINCT bp.bid_notice_id) AS participation_count,
           min(COALESCE(bp.bid_at,a.opening_at)::date) AS first_date,
           max(COALESCE(bp.bid_at,a.opening_at)::date) AS latest_date
    FROM public_procurement.bid_awards a
    JOIN public_procurement.bid_opening_participants bp
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    CROSS JOIN params p
    WHERE a.demand_organization_code=p.organization_code AND a.opening_at < p.as_of
    GROUP BY bp.business_registration_number
),
eligible_contracts AS (
    SELECT DISTINCT c.unified_contract_number, c.confirmed_contract_number,
           c.concluded_date, c.current_contract_amount,
           c.current_contract_amount_currency
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN params p
    WHERE d.organization_code=p.organization_code AND c.concluded_date < p.as_of::date
),
organization_contract_rows AS (
    SELECT cs.business_registration_number AS company_number, cs.supplier_name,
           c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''), c.unified_contract_number)
             AS contract_key,
           c.concluded_date,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS attributed_amount
    FROM eligible_contracts c
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE cs.business_registration_number IS NOT NULL
),
organization_contract_records AS (
    SELECT company_number, max(supplier_name) AS supplier_name, contract_key,
           count(DISTINCT unified_contract_number) AS unified_contract_count,
           max(attributed_amount) AS attributed_amount,
           bool_and(attributed_amount IS NOT NULL) AS amount_complete,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM organization_contract_rows
    GROUP BY company_number, contract_key
),
organization_contracts AS (
    SELECT company_number, max(supplier_name) AS company_name,
           count(*) AS contract_count,
           sum(unified_contract_count) AS unified_contract_count,
           sum(attributed_amount) AS contract_amount,
           bool_and(amount_complete) AS amount_complete,
           min(first_date) AS first_date, max(latest_date) AS latest_date
    FROM organization_contract_records GROUP BY company_number
),
candidates AS (
    SELECT company_number FROM similar_participations UNION
    SELECT company_number FROM similar_awards UNION
    SELECT company_number FROM similar_contracts UNION
    SELECT company_number FROM organization_awards UNION
    SELECT company_number FROM organization_contracts
)
SELECT c.company_number,
       COALESCE(op.company_name,oa.company_name,oc.company_name,
                sp.company_name,sa.company_name,sc.company_name) AS company_name,
       COALESCE(sp.participation_count,0) AS similar_participation_count,
       COALESCE(sa.award_count,0) AS similar_award_count,
       COALESCE(sc.contract_count,0) AS similar_contract_count,
       COALESCE(sc.unified_contract_count,0) AS similar_unified_contract_count,
       sa.award_amount AS similar_award_amount,
       sc.contract_amount AS similar_contract_amount,
       COALESCE(sc.amount_complete,false) AS similar_contract_amount_complete,
       sp.notice_ids AS participation_notice_ids,
       sa.notice_ids AS award_notice_ids,
       sc.notice_ids AS contract_notice_ids,
       LEAST(sp.first_date,sa.first_date,sc.first_date) AS similar_first_activity_date,
       GREATEST(sp.latest_date,sa.latest_date,sc.latest_date) AS similar_latest_activity_date,
       COALESCE(op.participation_count,0) AS organization_participation_count,
       COALESCE(oa.award_count,0) AS organization_award_count,
       COALESCE(oc.contract_count,0) AS organization_contract_count,
       COALESCE(oc.unified_contract_count,0) AS organization_unified_contract_count,
       oc.contract_amount AS organization_contract_amount,
       COALESCE(oc.amount_complete,false) AS contract_amount_complete,
       LEAST(op.first_date,oa.first_date,oc.first_date) AS organization_first_activity_date,
       GREATEST(op.latest_date,oa.latest_date,oc.latest_date) AS organization_latest_activity_date
FROM candidates c
LEFT JOIN similar_participations sp USING (company_number)
LEFT JOIN similar_awards sa USING (company_number)
LEFT JOIN similar_contracts sc USING (company_number)
LEFT JOIN organization_participations op USING (company_number)
LEFT JOIN organization_awards oa USING (company_number)
LEFT JOIN organization_contracts oc USING (company_number)
ORDER BY
  ((COALESCE(op.participation_count,0)+COALESCE(oa.award_count,0)+COALESCE(oc.contract_count,0)) > 0) DESC,
  COALESCE(sa.award_count,0) DESC,
  COALESCE(sc.contract_count,0) DESC,
  COALESCE(sp.participation_count,0) DESC,
  GREATEST(op.latest_date,oa.latest_date,oc.latest_date,
           sp.latest_date,sa.latest_date,sc.latest_date) DESC NULLS LAST,
  c.company_number
LIMIT %(limit)s
"""
