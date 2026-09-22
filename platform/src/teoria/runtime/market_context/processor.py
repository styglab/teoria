from __future__ import annotations

import asyncio
import json
import os
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
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            notice = connection.execute(
                """
                SELECT bid_notice_id, notice_number, notice_order, work_type,
                       demand_organization_code, demand_organization_name,
                       requirement_expression, extraction_completeness,
                       bid_deadline_at,
                       COALESCE(notice_published_at, bid_deadline_at, now()) AS as_of
                FROM public_procurement.runtime_bid_notices
                WHERE bid_notice_id = %s
                """,
                (bid_notice_id,),
            ).fetchone()
            if notice is None:
                raise LookupError(f"bid notice '{bid_notice_id}' was not found")
            if not notice["demand_organization_code"]:
                raise ValueError(f"bid notice '{bid_notice_id}' has no demand organization code")
            regions = list(connection.execute(
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
            requirements = list(connection.execute(
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
            rows = list(connection.execute(
                _RELEVANT_COMPANY_QUERY,
                {
                    "similar_notices": json.dumps(notice_pairs),
                    "organization_code": notice["demand_organization_code"],
                    "as_of": notice["as_of"],
                    "limit": limit,
                },
            ).fetchall())
        return (
            dict(notice), rows, [dict(item) for item in regions],
            [dict(item) for item in requirements],
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
            "organization_participation_count": item["organization_relationship"]["participation_count"],
            "organization_award_count": item["organization_relationship"]["award_count"],
            "organization_contract_count": item["organization_relationship"]["contract_count"],
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
            "award_amount": _number(row.get("similar_award_amount")),
            "contract_amount": _number(row.get("similar_contract_amount")),
            "matched_participation_bid_notice_ids": row.get("participation_notice_ids") or [],
            "matched_award_bid_notice_ids": row.get("award_notice_ids") or [],
            "matched_contract_bid_notice_ids": row.get("contract_notice_ids") or [],
            "first_activity_date": row.get("similar_first_activity_date"),
            "latest_activity_date": row.get("similar_latest_activity_date"),
        },
        "organization_relationship": {
            "organization_code": notice["demand_organization_code"],
            "organization_name": notice["demand_organization_name"],
            "participation_count": int(row.get("organization_participation_count") or 0),
            "award_count": int(row.get("organization_award_count") or 0),
            "contract_count": int(row.get("organization_contract_count") or 0),
            "contract_amount": _number(row.get("organization_contract_amount")),
            "contract_amount_basis": "supplier_attributed",
            "contract_amount_complete": bool(row.get("contract_amount_complete")),
            "first_activity_date": row.get("organization_first_activity_date"),
            "latest_activity_date": latest,
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
           sn.bid_notice_id, c.concluded_date,
           CASE WHEN cs.participation_share_rate IS NOT NULL
                THEN c.total_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.total_amount END AS attributed_amount
    FROM similar_notices sn
    JOIN public_procurement.contracts c ON c.notice_number=sn.notice_number
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    CROSS JOIN params p
    WHERE cs.business_registration_number IS NOT NULL
      AND c.concluded_date < p.as_of::date
),
similar_contracts AS (
    SELECT company_number, max(company_name) AS company_name,
           count(DISTINCT unified_contract_number) AS contract_count,
           sum(attributed_amount) AS contract_amount,
           array_agg(DISTINCT bid_notice_id ORDER BY bid_notice_id) AS notice_ids,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM similar_contract_rows GROUP BY company_number
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
    SELECT DISTINCT c.unified_contract_number, c.concluded_date, c.total_amount
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN params p
    WHERE d.organization_code=p.organization_code AND c.concluded_date < p.as_of::date
),
organization_contract_rows AS (
    SELECT cs.business_registration_number AS company_number, cs.supplier_name,
           c.unified_contract_number, c.concluded_date,
           CASE WHEN cs.participation_share_rate IS NOT NULL
                THEN c.total_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.total_amount END AS attributed_amount
    FROM eligible_contracts c
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE cs.business_registration_number IS NOT NULL
),
organization_contracts AS (
    SELECT company_number, max(supplier_name) AS company_name,
           count(DISTINCT unified_contract_number) AS contract_count,
           sum(attributed_amount) AS contract_amount,
           bool_and(attributed_amount IS NOT NULL) AS amount_complete,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM organization_contract_rows GROUP BY company_number
),
candidates AS (
    SELECT company_number FROM similar_participations UNION
    SELECT company_number FROM similar_awards UNION
    SELECT company_number FROM similar_contracts
)
SELECT c.company_number,
       COALESCE(op.company_name,oa.company_name,oc.company_name,
                sp.company_name,sa.company_name,sc.company_name) AS company_name,
       COALESCE(sp.participation_count,0) AS similar_participation_count,
       COALESCE(sa.award_count,0) AS similar_award_count,
       COALESCE(sc.contract_count,0) AS similar_contract_count,
       sa.award_amount AS similar_award_amount,
       sc.contract_amount AS similar_contract_amount,
       sp.notice_ids AS participation_notice_ids,
       sa.notice_ids AS award_notice_ids,
       sc.notice_ids AS contract_notice_ids,
       LEAST(sp.first_date,sa.first_date,sc.first_date) AS similar_first_activity_date,
       GREATEST(sp.latest_date,sa.latest_date,sc.latest_date) AS similar_latest_activity_date,
       COALESCE(op.participation_count,0) AS organization_participation_count,
       COALESCE(oa.award_count,0) AS organization_award_count,
       COALESCE(oc.contract_count,0) AS organization_contract_count,
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
