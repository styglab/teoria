from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
import time
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult

from ..bid_context.peer_benchmark import _representative_notice_amount
from ..bid_context.supplier_selection import (
    contract_time_relationship as _contract_time_relationship,
)
from ..field_identity import _normalized_category
from .filtering import RelatedProjectQuery, filter_and_page_related_projects
from ..periods import _shift_years
from ..readers import ProcurementProfileReader
from .similarity import (
    amount_similarity as _amount_similarity,
    business_fields as _business_fields,
    jaccard as _jaccard,
    number as _number,
    project_types as _project_types,
    title_tokens as _title_tokens,
)


async def execute_bid_related_projects_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_inputs = {**inputs, "processor_version": "1.2.2"}
    cache_key = cache.key(registry_version, capability_id, cache_inputs) if cache is not None else None
    cached = await cache.get(cache_key) if cache is not None and reader is None else None
    if cached is not None:
        cached.outcome["timings"] = {
            "total_ms": round((time.perf_counter()-started)*1000, 3), "cache_hit": True,
        }
        return cached
    bid_notice_id = str(inputs["bid_notice_id"])
    query = RelatedProjectQuery.from_inputs(inputs)
    resolved = reader or ProcurementProfileReader()
    try:
        notice, _ = await asyncio.to_thread(resolved.bid_context, catalog, bid_notice_id=bid_notice_id)
        cutoff = notice["notice_published_date"]
        period_from = _shift_years(cutoff, -3)
        filters = {"work_type": str(notice.get("work_type") or "unknown"),
            "large_category": _normalized_category(notice.get("large_category")),
            "middle_category": _normalized_category(notice.get("middle_category")),
            "field_code": str(notice.get("field_code") or "").strip() or None}
        contract_loader = getattr(resolved, "peer_field_contracts", None)
        if contract_loader:
            contracts = await asyncio.to_thread(contract_loader, catalog,
                period_from=period_from, period_to=cutoff,
                history_from=date(period_from.year - 3, 1, 1), **filters)
        else:
            contracts, _ = await asyncio.to_thread(resolved.peer_field_market, catalog,
            period_from=period_from, period_to=cutoff,
            history_from=date(period_from.year - 3, 1, 1), **filters)
    except LookupError as exc:
        raise CapabilityExecutionError("bid_notice_not_found", str(exc), capability_id=capability_id) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc
    organization_code = str(notice.get("organization_code") or "")
    scoped = [row for row in contracts if str(row.get("organization_code")) == organization_code]
    history: dict[str, list[date]] = {}
    for row in scoped:
        company = str(row.get("company_number") or "")
        if company: history.setdefault(company, []).append(row["first_contract_date"])
    current_amount, _ = _representative_notice_amount(notice)
    reference = Decimal(str(current_amount)) if current_amount is not None else None
    projects: dict[str, dict[str, Any]] = {}
    for row in scoped:
        event_date = row["first_contract_date"]
        if not period_from <= event_date < cutoff: continue
        event_id = str(row["event_key"]); company = str(row.get("company_number") or "")
        relationship = _contract_time_relationship(event_date, history.get(company, []))
        entry = relationship["contract_time_relationship_status"] == "entry_or_reentering"
        amount = row.get("contract_amount")
        similar = bool(reference and amount is not None
            and reference/Decimal("2") <= Decimal(str(amount)) <= reference*Decimal("2"))
        repeat = relationship["contract_time_relationship_status"] == "repeat"
        project_key = event_id or str(row.get("unified_contract_number") or "")
        item = projects.setdefault(project_key, {"bid_notice_id": row.get("bid_notice_id"),
            "notice_lineage_id": row.get("notice_lineage_id"),
            "root_bid_notice_id": row.get("root_bid_notice_id"),
            "notice_kind": row.get("notice_kind"), "lineage_count": row.get("lineage_count") or 1,
            "notice_name": row.get("notice_name") or row.get("contract_name"),
            "notice_published_at": None, "project_amount": _number(amount),
            "project_amount_basis": "contract_amount", "contract_event_id": event_id,
            "unified_contract_number": row.get("unified_contract_number"),
            "contract_amount": _number(amount), "contract_date": event_date,
            "first_contract_date": event_date,
            "latest_contract_version_date": row.get("latest_contract_version_date"),
            "contract_version_count": int(row.get("contract_version_count") or 1),
            "contractors": [], "is_similar_amount": similar,
            "entry_or_reentering_suppliers": [], "repeat_suppliers": [],
            "matched_filters": {"same_field"}, "amount_completeness": row.get("amount_completeness")})
        contractor = {"company_number": company, "company_name": row.get("company_name"),
            "company_role": row.get("company_role"), "share_percent": _number(row.get("share_percent")),
            "attributed_contract_amount": _number(row.get("attributed_contract_amount")),
            "supplier_entry_classification": "entry_or_reentering" if entry else "incumbent",
            "is_repeat_supplier": repeat, **relationship,
            "work_type": filters["work_type"], "field_code": filters["field_code"],
            "large_category": filters["large_category"],
            "middle_category": filters["middle_category"]}
        if company and all(value["company_number"] != company for value in item["contractors"]):
            item["contractors"].append(contractor)
        if entry and company: item["entry_or_reentering_suppliers"].append(company)
        if repeat and company: item["repeat_suppliers"].append(company)
        if similar: item["matched_filters"].add("similar_amount")
        if entry: item["matched_filters"].add("entry_or_reentering_supplier")
        if repeat: item["matched_filters"].add("repeat_supplier")
    items = list(projects.values())
    for item in items:
        statuses = {contractor["contract_time_relationship_status"]
            for contractor in item["contractors"]}
        item["relationship_status_summary"] = (
            next(iter(statuses)) if len(statuses) == 1 else "mixed"
        )
        item["contractor_count"] = len(item["contractors"])
        attributed_values = [contractor.get("attributed_contract_amount")
            for contractor in item["contractors"]]
        attributed_sum = sum((Decimal(str(value)) for value in attributed_values
            if value is not None), Decimal("0"))
        contract_amount = item.get("contract_amount")
        item["contractor_attributed_amount_sum"] = _number(attributed_sum)
        item["contractor_amount_difference"] = (
            _number(Decimal(str(contract_amount))-attributed_sum)
            if contract_amount is not None else None
        )
        item["contractor_amount_completeness"] = (
            "unknown" if contract_amount is None
            else "partial" if any(value is None for value in attributed_values)
                or Decimal(str(contract_amount)) != attributed_sum
            else "complete"
        )
        item["entry_or_reentering_suppliers"] = sorted(set(item["entry_or_reentering_suppliers"]))
        item["repeat_suppliers"] = sorted(set(item["repeat_suppliers"]))
    result_page = filter_and_page_related_projects(items, query, reference_amount=reference)
    result = CapabilityResult(capability_id=capability_id, outcome={**result_page,
        "analysis_basis": {"bid_notice_id": bid_notice_id, "organization_code": organization_code,
            "period_from": period_from, "period_to": cutoff-timedelta(days=1), "field_filter": filters,
            "event_unit": "procurement_project"},
        "registry_version": registry_version,
        "timings": {"total_ms": round((time.perf_counter()-started)*1000, 3),
            "cache_hit": False}})
    if cache is not None and reader is None:
        await cache.set(cache_key, result, 600)
    return result


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
