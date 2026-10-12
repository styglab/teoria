from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from teoria.domains.public_procurement.bid_eligibility.models import (
    CompanyEvidenceSnapshot,
    requirement_value,
)
from teoria.domains.public_procurement.bid_eligibility.outcomes import evaluate_requirement_category
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult
from teoria.runtime.mapping.materializer import MaterializedObject

from .related_projects.similarity import compact as _compact, number as _number
from .signal_policy import RECENT_ACTIVITY_DAYS


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
