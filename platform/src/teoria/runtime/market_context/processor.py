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
ORGANIZATION_FIELD_CACHE_TTL_SECONDS = 600
_ORGANIZATION_FIELD_CACHE: dict[tuple[str, int, int, str], tuple[float, CapabilityResult]] = {}


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
                       notice_name, work_type, contract_method_name,
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
            notice["industry_codes"] = [str(row["industry_code"]) for row in connection.execute(
                """
                SELECT DISTINCT substring(license_restriction_name FROM '/([0-9]{4})$')
                       AS industry_code
                FROM public_procurement.bid_notice_license_restrictions
                WHERE notice_number=%s AND notice_order=%s
                  AND license_restriction_name ~ '/[0-9]{4}$'
                ORDER BY industry_code
                """,
                tuple(str(notice["bid_notice_id"]).rsplit(":", 1)),
            ).fetchall()]
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
            similar_kwargs["candidate_limit"] = 200
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
        company_kwargs: dict[str, Any] = {"limit": max(limit * 10, 200)}
        if company_reader is None:
            company_kwargs["timings"] = timings
            company_kwargs["award_contract_only"] = True
        relationship_notice, rows, _, _ = await asyncio.to_thread(
            resolved_company_reader.find_relevant,
            catalog, bid_notice_id, selected_ids, **company_kwargs,
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

    aggregation_started = time.perf_counter()
    groups: dict[str, list[dict[str, Any]]] = {
        "organization_field_companies": [],
        "market_similar_companies": [],
        "organization_other_companies": [],
    }
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

    def ranking(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            item["same_field_award_count"] + item["same_field_contract_count"],
            item["same_project_type_count"], item["similar_amount_count"],
            item["same_organization_award_count"] + item["same_organization_contract_count"],
            item["latest_activity_date"] or date.min,
        )

    for values in groups.values():
        values.sort(key=ranking, reverse=True)
        del values[limit:]
    all_items = [
        *groups["organization_field_companies"],
        *groups["market_similar_companies"],
        *groups["organization_other_companies"],
    ]
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
    timings["contract_attribution_ms"] = 0.0
    timings["total_ms"] = (time.perf_counter() - total_started) * 1000
    timings = {key: round(value, 3) for key, value in timings.items()}
    timings["cache_hit"] = False
    result = CapabilityResult(
        capability_id=capability_id, objects=objects,
        outcome={
            "bid_notice_id": bid_notice_id,
            "organization": {
                "code": relationship_notice["demand_organization_code"],
                "name": relationship_notice["demand_organization_name"],
            },
            **groups,
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


def _project_types(value: str) -> set[str]:
    patterns = {
        "build": ("구축", "개발", "도입"),
        "improvement": ("고도화", "개선", "재구축"),
        "maintenance": ("유지보수", "유지관리", "운영"),
        "consulting": ("컨설팅", "감리", "설계"),
    }
    compact = _compact(value)
    return {kind for kind, words in patterns.items() if any(word in compact for word in words)}


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
      AND n.notice_published_at >= %(as_of)s::timestamptz - (%(period_years)s * interval '1 year')
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
      AND n.notice_published_at >= %(as_of)s::timestamptz - (%(period_years)s * interval '1 year')
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
  AND a.opening_at >= %(as_of)s::timestamptz - (%(period_years)s * interval '1 year')
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
