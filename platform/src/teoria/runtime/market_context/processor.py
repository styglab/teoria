from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
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
from teoria.runtime.procurement_classification import (
    decorate_field_distribution,
    field_identity,
    normalize_category,
)
from teoria.runtime.provenance import Provenance

from .attention import (
    build_attention_suppliers as _build_attention_suppliers,
    contract_time_relationship as _contract_time_relationship,
)
from .related_projects import RelatedProjectQuery, filter_and_page_related_projects
from .similarity import (
    TITLE_TRIGRAM_SIMILARITY_THRESHOLD,
    amount_similarity as _amount_similarity,
    business_fields as _business_fields,
    character_trigrams as _character_trigrams,
    compact as _compact,
    jaccard as _jaccard,
    normalized_title as _normalized_title,
    number as _number,
    primary_project_type as _primary_project_type,
    project_type_label as _project_type_label,
    project_types as _project_types,
    title_tokens as _title_tokens,
    work_type_label as _work_type_label,
)
from .readers import (
    BidNoticeParticipationReader,
    CompanyParticipationReader,
    CompanySimilarProjectExperienceReader,
    ContractSupplierBatchReader,
    OrganizationFieldEventReader,
    ProcurementActivityReader,
    ProcurementOutcomeReader,
    ProcurementProfileReader,
    SimilarBidNoticeReader,
)
from .queries import (
    _BID_CONTEXT_COMPETITION_QUERY,
    _BID_CONTEXT_PEER_COMPETITION_QUERY,
    _BID_CONTEXT_PEER_CONTRACTS_QUERY,
    _BID_NOTICE_PARTICIPATIONS_QUERY,
    _BID_RELATIONSHIP_NOTICE_QUERY,
    _BID_RELATIONSHIP_PARTICIPANTS_QUERY,
    _COMPANY_COMPETITORS_QUERY,
    _COMPANY_PARTICIPATIONS_QUERY,
    _COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY,
    _COMPANY_SIMILAR_PROJECT_METRICS_QUERY,
    _COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY,
    _CONTRACT_SUPPLIERS_BATCH_QUERY,
    _ORGANIZATION_AWARD_CONTRACT_ACTIVITIES_QUERY,
    _ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY,
    _ORGANIZATION_FIELD_EVENT_ROWS_QUERY,
    _ORGANIZATION_RELATIONSHIP_ACTIVITIES_QUERY,
    _PROCUREMENT_ACTIVITY_COMPANY_PARTICIPATION_QUERY,
    _PROCUREMENT_ACTIVITY_NOTICES_QUERY,
    _PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY,
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
    _PROCUREMENT_OUTCOME_CONTRACTS_QUERY,
    _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
    _PROCUREMENT_PROFILE_NOTICES_QUERY,
    _SIMILAR_NOTICE_CANDIDATES_QUERY,
)


SIGNAL_POLICY_VERSION = "1.0.0"
RECENT_ACTIVITY_DAYS = 365
SIMILARITY_PROFILE = "bid_comparison_v1"
ORGANIZATION_FIELD_CACHE_TTL_SECONDS = 600
_ORGANIZATION_FIELD_CACHE: dict[tuple[str, int, int, str], tuple[float, CapabilityResult]] = {}
_ORGANIZATION_COMPANY_FIELD_CACHE: dict[tuple[Any, ...], tuple[float, CapabilityResult]] = {}
_BID_PARTICIPATION_CONTEXT_CACHE: dict[tuple[str, int, str], tuple[float, CapabilityResult]] = {}



async def enrich_contract_search_objects(
    catalog: RegistryCatalog, objects: list[MaterializedObject], *, observed_at: datetime,
    reader: ContractSupplierBatchReader | None = None,
) -> None:
    """Attach contractors to the already paginated contract page in one DB query."""
    contracts = [item for item in objects if item.object_type == "contract"]
    contract_numbers = [
        str(item.properties.get("unified_contract_number") or "").strip()
        for item in contracts
    ]
    contract_numbers = [value for value in contract_numbers if value]
    if not contract_numbers:
        return
    resolved_reader = reader or ContractSupplierBatchReader()
    rows = await asyncio.to_thread(
        resolved_reader.find, catalog, unified_contract_numbers=contract_numbers,
    )
    grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in contract_numbers}
    record_keys: dict[str, list[str]] = {value: [] for value in contract_numbers}
    for row in rows:
        contract_number = str(row["unified_contract_number"])
        is_joint = bool(row.get("is_joint_contract"))
        source_role = str(row.get("supplier_role_name") or "").strip()
        if not is_joint:
            role, role_label = "sole", "단독"
        elif source_role == "주계약업체":
            role, role_label = "consortium_lead", "대표사"
        else:
            role, role_label = "consortium_member", "구성원"
        raw_share = row.get("participation_share_rate")
        valid_share = raw_share is not None and Decimal("0") <= Decimal(str(raw_share)) <= Decimal("100")
        grouped.setdefault(contract_number, []).append({
            "business_registration_number": row.get("business_registration_number"),
            "company_name": row.get("supplier_name"),
            "company_role": role,
            "company_role_label": role_label,
            "source_role_name": source_role or None,
            "joint_contract_method_name": row.get("joint_contract_method_name"),
            "share_percent": _number(Decimal(str(raw_share))) if valid_share else None,
            "share_completeness": (
                "complete" if valid_share else "invalid" if raw_share is not None else "unknown"
            ),
        })
        record_keys.setdefault(contract_number, []).append(
            f"teoria_public_procurement.contract_suppliers:"
            f"{contract_number}:{row.get('supplier_sequence')}"
        )
    by_number = {
        str(item.properties.get("unified_contract_number")): item for item in contracts
    }
    for contract_number in contract_numbers:
        contract = by_number[contract_number]
        contractors = grouped.get(contract_number, [])
        lead = next(
            (item for item in contractors if item["company_role"] == "consortium_lead"),
            None,
        )
        contract.properties.update({
            "contractors": contractors,
            "contractor_count": len(contractors),
            "lead_contractor": lead,
            "contractor_completeness": "complete" if contractors else "unknown",
        })
        provenance = Provenance(
            kind="source", source="teoria_public_procurement",
            operation="contract_suppliers", mapping="public_procurement",
            observed_at=observed_at, record_keys=record_keys.get(contract_number, []),
        )
        contract.provenance.append(provenance)
        for key in (
            "contractors", "contractor_count", "lead_contractor",
            "contractor_completeness",
        ):
            contract.property_provenance[key] = [provenance]



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
    cache: Any | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    organization_code = str(inputs["organization_code"])
    company_number = "".join(
        character for character in str(inputs["business_registration_number"])
        if character.isdigit()
    )
    field_code = str(inputs["field_code"]) if inputs.get("field_code") else None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    procurement_field_code = (
        str(inputs["procurement_field_code"]).strip()
        if inputs.get("procurement_field_code") else None
    )
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
    (
        resolved_period_from, resolved_period_to, period_years, resolved_period_type,
        resolved_from_year, resolved_to_year,
    ) = _resolve_profile_period(
        {**inputs, "period_years": inputs.get("period_years", 10)},
        capability_id=capability_id,
    )
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
        reference_bid_notice_id, work_type, large_category, middle_category,
        procurement_field_code, registry_version, resolved_period_from, resolved_period_to,
    )
    shared_cache_key = (
        cache.key(registry_version, capability_id, {"cache_key": cache_key})
        if cache is not None else cache_key
    )
    shared_cached = await cache.get(shared_cache_key) if cache is not None else None
    cached = _ORGANIZATION_COMPANY_FIELD_CACHE.get(cache_key) if cache is None else None
    if shared_cached is not None or (
        cached and time.monotonic() - cached[0] < ORGANIZATION_FIELD_CACHE_TTL_SECONDS
    ):
        result = shared_cached or cached[1].model_copy(deep=True)
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
            resolved_period_to, datetime.min.time(), timezone.utc
        )
        find_inputs: dict[str, Any] = {
            "organization_code": organization_code,
            "work_type": work_type,
            "as_of": as_of,
        }
        if large_category or middle_category or procurement_field_code:
            find_inputs.update({
                "large_category": large_category,
                "middle_category": middle_category,
                "procurement_field_code": procurement_field_code,
            })
        rows = await asyncio.to_thread(resolved_reader.find, catalog, **find_inputs)
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
        attribution_date = event.get("attribution_date") or event.get("awarded_at")
        if "contract" in event["source_kinds"] and attribution_date \
                and period_start <= attribution_date < as_of_date:
            contract_event_count += 1
            contract_version_count += len(set(
                event["members"][company_number].get("contract_activity_dates") or []
            ))

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
            "attribution_date": event.get("attribution_date"),
            "attribution_date_basis": event.get("attribution_date_basis"),
            "award_date": event.get("award_date"),
            "contract_date": event.get("contract_date"),
            "first_contract_date": event.get("first_contract_date"),
            "latest_contract_version_date": event.get("latest_contract_version_date"),
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
                "period_from_year": resolved_from_year or period_start.year,
                "period_to_year": resolved_to_year or (as_of_date - timedelta(days=1)).year,
                "period_type": resolved_period_type,
                "work_type": work_type,
                "reference_bid_notice_id": reference_bid_notice_id,
                "event_attribution": "notice_published_at_or_first_contract_date",
                "contract_amount_version": "latest_at_or_before_period_end",
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
    if cache is not None:
        await cache.set(shared_cache_key, result, ORGANIZATION_FIELD_CACHE_TTL_SECONDS)
    else:
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
    cache: Any | None = None,
) -> CapabilityResult:
    """Return complete company×organization history without field filtering."""
    history_inputs = {
        "organization_code": inputs["organization_code"],
        "business_registration_number": inputs["business_registration_number"],
        "work_type": inputs.get("work_type"),
        "large_category": inputs.get("large_category"),
        "middle_category": inputs.get("middle_category"),
        "procurement_field_code": inputs.get("field_code"),
        "period_years": inputs.get("period_years", 10),
        "period_from_year": inputs.get("period_from_year"),
        "period_to_year": inputs.get("period_to_year"),
        "page": inputs.get("page", 1),
        "page_size": inputs.get("page_size", 20),
    }
    result = await execute_organization_company_field_relationship(
        catalog,
        "get_organization_company_field_relationship",
        history_inputs,
        reader=reader,
        cache=cache,
    )
    result.capability_id = capability_id
    result.outcome["relationship_type"] = "organization_history"
    result.outcome["analysis_basis"].update({
        "field_filter_applied": any(inputs.get(key) for key in (
            "large_category", "middle_category", "field_code",
        )),
        "field_filter": {
            "large_category": _normalized_category(inputs.get("large_category")),
            "middle_category": _normalized_category(inputs.get("middle_category")),
            "field_code": str(inputs.get("field_code") or "").strip() or None,
        },
        "similarity_assessment_applied": False,
    })
    result.outcome.pop("field", None)
    result.outcome["yearly_activity"] = result.outcome.pop("annual_activity")
    for event in result.outcome["events"]:
        event["organization_match"] = True
        event.pop("field_match_reasons", None)
    profile = None
    if reader is None:
        profile = await _execute_procurement_profile(
            catalog, "analyze_organization_procurement_profile", {
                "organization_code": inputs["organization_code"],
                "business_registration_number": inputs["business_registration_number"],
                "period_years": inputs.get("period_years", 10),
                "period_from_year": inputs.get("period_from_year"),
                "period_to_year": inputs.get("period_to_year"),
                "work_type": inputs.get("work_type"),
                "large_category": inputs.get("large_category"),
                "middle_category": inputs.get("middle_category"),
                "field_code": inputs.get("field_code"),
                "page": 1, "page_size": 1,
            }, profile_type="organization",
        )
    relationships = (profile.outcome.get("company_relationships") or []) if profile else []
    relationship = relationships[0] if relationships else None
    if relationship:
        result.outcome["summary"].update({
            key: relationship[key] for key in (
                "award_event_count", "contract_event_count", "contract_version_count",
                "unique_project_count", "total_attributed_contract_amount",
                "amount_completeness", "active_years", "active_year_count",
                "first_activity_date", "latest_activity_date", "latest_contract_date",
            )
        })
        result.outcome["yearly_activity"] = relationship["yearly_activity"]
        result.outcome["major_fields"] = relationship["major_fields"]
        result.outcome["project_type_distribution"] = relationship[
            "project_type_distribution"
        ]
    elif profile is not None:
        result.outcome["summary"].update({
            "award_event_count": 0, "contract_event_count": 0,
            "contract_version_count": 0, "unique_project_count": 0,
            "total_attributed_contract_amount": 0, "amount_completeness": "unknown",
            "active_years": [], "active_year_count": 0,
            "first_activity_date": None, "latest_activity_date": None,
            "latest_contract_date": None,
        })
        result.outcome["yearly_activity"] = []
        result.outcome["major_fields"] = []
        result.outcome["project_type_distribution"] = []
    if profile is not None:
        result.outcome["analysis_basis"].update({
            key: profile.outcome["analysis_basis"][key]
            for key in (
                "period_from", "period_to", "period_from_year", "period_to_year",
                "period_years", "period_type", "event_attribution",
                "contract_amount_version",
            )
        })
        contract_events = profile.outcome.pop("_relationship_contract_events", [])
        total_events = len(contract_events)
        requested_page = int(inputs.get("page", 1))
        requested_page_size = int(inputs.get("page_size", 20))
        offset = (requested_page - 1) * requested_page_size
        result.outcome["events"] = contract_events[offset:offset + requested_page_size]
        result.outcome["pagination"] = {
            "page": requested_page, "page_size": requested_page_size,
            "total_items": total_events,
            "total_pages": (total_events + requested_page_size - 1) // requested_page_size,
        }
        result.outcome["summary"]["linked_notice_count"] = len({
            item["bid_notice_id"] for item in contract_events
            if item.get("bid_notice_id") and item.get("notice_linkage") == "linked"
        })
        result.outcome["summary"]["unlinked_contract_count"] = sum(
            item.get("notice_linkage") == "unlinked"
            for item in contract_events
        )
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
    return normalize_category(value)


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
            if large_category and _normalized_category(
                field_identity.get("large_category")
            ) != large_category:
                continue
            if middle_category and _normalized_category(
                field_identity.get("middle_category")
            ) != middle_category:
                continue
            if field_code and str(field_identity.get("code") or "") != field_code:
                continue
        filtered.append(row)
    return filtered


def _contract_project_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identify one logical contract relationship independently of its versions."""
    event_key = str(row.get("event_key") or "").strip()
    notice_id = str(row.get("bid_notice_id") or "").strip()
    contract_event_id = event_key or notice_id
    return (
        str(row.get("organization_code") or ""),
        str(row.get("company_number") or ""),
        str(row.get("work_type") or "unknown"),
        contract_event_id,
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
        latest = max(versions, key=lambda row: (
            row.get("latest_contract_version_date")
            or row.get("activity_date") or date.min
        ))
        collapsed = dict(latest)
        first_contract_dates = [
            (
                row["first_contract_date"]
                if "first_contract_date" in row
                else row.get("activity_date")
            )
            for row in versions
            if (
                row.get("first_contract_date") is not None
                or (
                    "first_contract_date" not in row
                    and row.get("activity_date") is not None
                )
            )
        ]
        first_contract_date = min(first_contract_dates) if first_contract_dates else None
        collapsed["first_contract_date"] = first_contract_date
        collapsed["activity_date"] = first_contract_date
        collapsed["attribution_date_basis"] = "first_contract_date"
        collapsed["contract_version_count"] = sum(
            int(row.get("contract_version_count") or 1) for row in versions
        )
        version_dates = {
            value
            for row in versions
            for value in (
                row.get("contract_version_dates")
                or [row.get("latest_contract_version_date")]
            )
            if value
        }
        collapsed["contract_version_dates"] = sorted(version_dates)
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
    if work_type == "goods":
        return ("detail" if field_code else "field"), fields
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
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
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
            "result_confirmed_participation_count", "successful_participation_count",
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
        item["award_success_rate"] = (
            round(item["successful_participation_count"] /
                  item["result_confirmed_participation_count"], 6)
            if item["result_confirmed_participation_count"] else None
        )
        item["work_types"] = sorted(item["work_types"])
        distribution.append(item)
    distribution.sort(key=lambda item: item["event_count"], reverse=True)
    return level, distribution


def _profile_aggregate(
    rows: list[dict[str, Any]], *, relationship_dimension: str,
    require_contract_relationship: bool = False,
    notice_rows: list[dict[str, Any]] | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
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
    notice_dates: dict[str, date] = {}
    classified_notice_ids: set[str] = set()
    participant_event_keys: set[tuple[str, str]] = set()
    confirmed_participant_event_keys: set[tuple[str, str]] = set()
    successful_participant_event_keys: set[tuple[str, str]] = set()
    award_event_keys: set[str] = set()
    contract_event_keys: set[str] = set()
    project_keys: set[tuple[str, str]] = set()
    contract_version_count = 0
    companies = set()
    organizations = set()
    total_amount = Decimal("0")
    amount_statuses: list[str] = []

    def year_bucket(value: date) -> dict[str, Any]:
        return yearly.setdefault(value.year, {
            "year": value.year, "notice_ids": set(), "company_ids": set(),
            "participation_keys": set(), "confirmed_participation_keys": set(),
            "successful_participation_keys": set(),
            "award_event_keys": set(), "contract_event_keys": set(),
            "attributed_contract_amount": Decimal("0"), "amount_statuses": [],
        })

    def register_notice(row: dict[str, Any]) -> None:
        notice_id = str(row.get("bid_notice_id") or "").strip()
        published = row.get("notice_published_date")
        if isinstance(published, datetime):
            published = published.date()
        if not notice_id or not isinstance(published, date):
            return
        if period_from is not None and published < period_from:
            return
        if period_to is not None and published >= period_to:
            return
        current = notice_dates.get(notice_id)
        notice_dates[notice_id] = min(current, published) if current else published
        if _procurement_field_identity(row):
            classified_notice_ids.add(notice_id)

    for notice_row in notice_rows or []:
        register_notice(notice_row)

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
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
            "contract_event_count": 0,
            "contract_version_count": 0, "project_keys": set(),
            "total_attributed_contract_amount": Decimal("0"),
            "amount_statuses": [], "dates": [], "contract_dates": [], "years": set(),
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
        # Activity years describe the procurement cohort, not amendment dates.
        relationship_dates = [activity_date]
        relationship["dates"].extend(relationship_dates)
        relationship["years"].update(value.year for value in relationship_dates)
        if activity_type == "contract":
            relationship["contract_dates"].append(
                row.get("latest_contract_version_date") or activity_date
            )
        year_item = relationship["yearly"].setdefault(activity_date.year, {
            "year": activity_date.year, "participation_count": 0,
            "result_confirmed_participation_count": 0,
            "successful_participation_count": 0,
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
            participant_key = (key, str(row["event_key"]))
            participant_event_keys.add(participant_key)
            if row.get("result_confirmed"):
                confirmed_participant_event_keys.add(participant_key)
                relationship["result_confirmed_participation_count"] += 1
                year_item["result_confirmed_participation_count"] += 1
            if row.get("participation_successful"):
                successful_participant_event_keys.add(participant_key)
                relationship["successful_participation_count"] += 1
                year_item["successful_participation_count"] += 1
        register_notice(row)
        companies.add(str(row.get("company_number") or ""))
        organizations.add(str(row.get("organization_code") or ""))
        relationship["representative_notices"].append({
            "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
            "activity_type": activity_type, "activity_date": activity_date,
            "amount": _number(amount if activity_type == "contract" else row.get("event_amount")),
            "attribution_date": activity_date,
            "attribution_date_basis": row.get("attribution_date_basis"),
            "first_contract_date": row.get("first_contract_date"),
            "latest_contract_version_date": row.get("latest_contract_version_date"),
        })
        field_identity = _procurement_field_identity(row)
        if not field_identity:
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
            "event_keys": set(), "participation_keys": set(),
            "confirmed_participation_keys": set(), "successful_participation_keys": set(),
            "award_event_keys": set(), "contract_event_keys": set(),
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
        event_key = str(row["event_key"])
        field["event_keys"].add((activity_type, event_key))
        field["work_types"].add(work_type)
        field[{
            "participation": "participation_keys",
            "award": "award_event_keys",
            "contract": "contract_event_keys",
        }[activity_type]].add((key, event_key) if activity_type == "participation" else event_key)
        if activity_type == "participation" and row.get("result_confirmed"):
            field["confirmed_participation_keys"].add((key, event_key))
        if activity_type == "participation" and row.get("participation_successful"):
            field["successful_participation_keys"].add((key, event_key))
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

        global_year = year_bucket(activity_date)
        if activity_type == "award":
            global_year["award_event_keys"].add(str(row["event_key"]))
        elif activity_type == "contract":
            global_year["company_ids"].add(str(row.get("company_number") or ""))
            global_year["contract_event_keys"].add(str(row["event_key"]))
            global_year["amount_statuses"].append(completeness)
            if amount is not None:
                global_year["attributed_contract_amount"] += Decimal(str(amount))
        else:
            participant_key = (key, str(row["event_key"]))
            global_year["participation_keys"].add(participant_key)
            if row.get("result_confirmed"):
                global_year["confirmed_participation_keys"].add(participant_key)
            if row.get("participation_successful"):
                global_year["successful_participation_keys"].add(participant_key)

    for notice_id, published in notice_dates.items():
        year_bucket(published)["notice_ids"].add(notice_id)

    relationship_items = []
    for relationship in relationships.values():
        if require_contract_relationship and relationship["contract_event_count"] <= 0:
            continue
        relation_yearly = []
        for value in sorted(relationship.pop("yearly").values(), key=lambda x: x["year"]):
            statuses = value.pop("amount_statuses")
            value["attributed_contract_amount"] = _number(value["attributed_contract_amount"])
            value["amount_completeness"] = _amount_completeness(statuses)
            confirmed = value["result_confirmed_participation_count"]
            value["award_success_rate"] = (
                round(value["successful_participation_count"] / confirmed, 6)
                if confirmed else None
            )
            relation_yearly.append(value)
        statuses = relationship.pop("amount_statuses")
        dates = relationship.pop("dates")
        contract_dates = relationship.pop("contract_dates")
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
            "latest_contract_date": max(contract_dates) if contract_dates else None,
            "active_years": years, "active_year_count": len(years),
            "unique_project_count": len(relationship.pop("project_keys")),
            "yearly_activity": relation_yearly,
            "major_fields": major_fields,
            "major_field": ({
                "field_code": max(
                    major_fields, key=lambda item: (item["amount"] or 0, item["event_count"])
                )["code"],
                "field_name": max(
                    major_fields, key=lambda item: (item["amount"] or 0, item["event_count"])
                )["name"],
            } if major_fields else None),
            "project_type_distribution": project_types,
            "representative_notices": sorted(
                relationship["representative_notices"],
                key=lambda item: item["activity_date"], reverse=True,
            )[:3],
        })
        confirmed = relationship["result_confirmed_participation_count"]
        relationship["award_success_rate"] = (
            round(relationship["successful_participation_count"] / confirmed, 6)
            if confirmed else None
        )
        relationship_items.append(relationship)
    yearly_items = []
    for year in sorted(yearly, reverse=True):
        value = yearly[year]
        yearly_items.append({
            "year": year, "notice_count": len(value["notice_ids"]),
            "participation_count": len(value["participation_keys"]),
            "result_confirmed_participation_count": len(value["confirmed_participation_keys"]),
            "successful_participation_count": len(value["successful_participation_keys"]),
            "award_success_rate": (
                round(len(value["successful_participation_keys"]) /
                      len(value["confirmed_participation_keys"]), 6)
                if value["confirmed_participation_keys"] else None
            ),
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
        value["participation_count"] = len(value.pop("participation_keys"))
        value["result_confirmed_participation_count"] = len(
            value.pop("confirmed_participation_keys")
        )
        successful = len(value.pop("successful_participation_keys"))
        value["successful_participation_count"] = successful
        value["award_success_rate"] = (
            round(successful / value["result_confirmed_participation_count"], 6)
            if value["result_confirmed_participation_count"] else None
        )
        value["award_event_count"] = len(value.pop("award_event_keys"))
        value["contract_event_count"] = len(value.pop("contract_event_keys"))
        value["attributed_contract_amount"] = _number(amount)
        value["amount_share"] = (
            round(float(amount / total_amount), 6) if total_amount else None
        )
        field_items.append(value)
    summary = {
        "notice_count": len(notice_dates), "participation_count": len(participant_event_keys),
        "result_confirmed_participation_count": len(confirmed_participant_event_keys),
        "successful_participation_count": len(successful_participant_event_keys),
        "award_event_count": len(award_event_keys),
        "contract_event_count": len(contract_event_keys),
        "contract_version_count": contract_version_count,
        "unique_project_count": len(project_keys),
        "company_count": (
            len(relationship_items) if require_contract_relationship
            else len(companies - {""})
        ),
        "organization_count": len(organizations - {""}),
        "total_attributed_contract_amount": _number(total_amount),
        "amount_completeness": _amount_completeness(amount_statuses),
        "classified_notice_count": len(classified_notice_ids),
        "field_classification_completeness": (
            "complete" if notice_dates and classified_notice_ids == set(notice_dates)
            else "partial" if classified_notice_ids else "unknown"
        ),
    }
    summary["award_success_rate"] = (
        round(len(successful_participant_event_keys) /
              len(confirmed_participant_event_keys), 6)
        if confirmed_participant_event_keys else None
    )
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


def _resolve_profile_period(
    inputs: dict[str, Any], *, capability_id: str,
) -> tuple[date, date, int, str, int | None, int | None]:
    """Resolve a profile window as a half-open date range.

    Explicit years override ``period_years`` and represent complete calendar
    years.  The current year is capped at today so a response never claims to
    cover future activity.
    """
    from_value = inputs.get("period_from_year")
    to_value = inputs.get("period_to_year")
    if (from_value is None) != (to_value is None):
        raise CapabilityExecutionError(
            "invalid_period_range",
            "period_from_year and period_to_year must be provided together",
            capability_id=capability_id,
        )
    today = date.today()
    if from_value is not None:
        from_year = int(from_value)
        to_year = int(to_value)
        if from_year > to_year:
            raise CapabilityExecutionError(
                "invalid_period_range",
                "period_from_year must be less than or equal to period_to_year",
                capability_id=capability_id,
            )
        if to_year > today.year:
            raise CapabilityExecutionError(
                "invalid_period_range",
                "period_to_year cannot be later than the current year",
                capability_id=capability_id,
            )
        return (
            date(from_year, 1, 1),
            min(date(to_year + 1, 1, 1), today + timedelta(days=1)),
            to_year - from_year + 1,
            "explicit_calendar_year_range",
            from_year,
            to_year,
        )
    period_years = int(inputs.get("period_years", 5))
    return (
        _fiscal_period_start(today, period_years), today + timedelta(days=1),
        period_years, "calendar_fiscal_years", None, None,
    )


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
        attribution_date = row.get("activity_date")
        if not attribution_date:
            continue
        if period_from <= attribution_date < period_to:
            current_companies.add(company_number)
        elif comparison_period_from <= attribution_date < period_from:
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
        "classified_company_count": len(first_observed | reentering | incumbent),
        "first_observed_company_rate": round(len(first_observed) / total, 6) if total else None,
        "entry_and_reentry_rate": round(entry_count / total, 6) if total else None,
        "history_from": history_available_from,
        "history_to": period_from - timedelta(days=1),
        "history_years": 5,
        "history_basis": "five_fiscal_years_before_target_period",
        "minimum_sample_size": 10,
        "sample_sufficient": total >= 10,
    }


def _supplier_entry(
    rows: list[dict[str, Any]], *, target_year: int, period_to: date,
    history_available_from: date | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Classify target-year contract suppliers against three prior calendar years."""
    target_from = date(target_year, 1, 1)
    target_to_exclusive = min(date(target_year + 1, 1, 1), period_to)
    lookback_from = date(target_year - 3, 1, 1)
    lookback_to_exclusive = target_from
    by_company: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("activity_type") != "contract" or not row.get("activity_date"):
            continue
        company_number = str(row.get("company_number") or "").strip()
        if company_number:
            by_company.setdefault(company_number, []).append(row)

    companies = []
    status_names = {
        "first_observed": "신규 관측", "reentering": "재진입", "incumbent": "기존",
    }
    for company_number, company_rows in by_company.items():
        target_rows = [
            row for row in company_rows
            if target_from <= row["activity_date"] < target_to_exclusive
        ]
        if not target_rows:
            continue
        prior_rows = [row for row in company_rows if row["activity_date"] < target_from]
        lookback_rows = [
            row for row in prior_rows
            if lookback_from <= row["activity_date"] < lookback_to_exclusive
        ]
        if lookback_rows:
            status = "incumbent"
        elif prior_rows:
            status = "reentering"
        else:
            status = "first_observed"
        event_keys = {str(row.get("event_key") or "") for row in target_rows}
        target_amounts = [
            Decimal(str(row["attributed_contract_amount"]))
            for row in target_rows if row.get("attributed_contract_amount") is not None
        ]
        # Entry classification remains based on procurement attribution dates,
        # while every public `contract_date` field uses the original contract
        # event date.  Amendment/installment version dates are not substituted.
        target_contract_dates = [
            row["first_contract_date"] for row in target_rows
            if row.get("first_contract_date") is not None
        ]
        prior_contract_dates = [
            row["first_contract_date"] for row in prior_rows
            if row.get("first_contract_date") is not None
        ]
        all_contract_dates = [
            row["first_contract_date"] for row in company_rows
            if row.get("first_contract_date") is not None
        ]
        named = next(
            (row.get("company_name") for row in target_rows if row.get("company_name")), None
        )
        companies.append({
            "company_number": company_number, "company_name": named,
            "entry_status": status, "entry_status_name": status_names[status],
            "target_year_contract_count": len(event_keys),
            "target_year_attributed_contract_amount": _number(sum(target_amounts, Decimal("0"))),
            "amount_completeness": _amount_completeness([
                str(row.get("amount_completeness") or "unknown") for row in target_rows
            ]),
            "target_year_first_contract_date": (
                min(target_contract_dates) if target_contract_dates else None
            ),
            "target_year_latest_contract_date": (
                max(target_contract_dates) if target_contract_dates else None
            ),
            "first_observed_contract_date": (
                min(all_contract_dates) if all_contract_dates else None
            ),
            "previous_contract_date": (
                max(prior_contract_dates) if prior_contract_dates else None
            ),
            "reentry_contract_date": (
                min(target_contract_dates)
                if status == "reentering" and target_contract_dates else None
            ),
        })
    companies.sort(
        key=lambda item: (
            item["target_year_attributed_contract_amount"] or 0,
            item["target_year_contract_count"], item["company_number"],
        ), reverse=True,
    )
    counts = {
        status: sum(item["entry_status"] == status for item in companies)
        for status in status_names
    }
    total = len(companies)
    entry_count = counts["first_observed"] + counts["reentering"]
    history_complete = (
        history_available_from is not None and history_available_from <= lookback_from
    )
    summary = {
        "target_year": target_year,
        "period_from": target_from,
        "period_to": target_to_exclusive - timedelta(days=1),
        "lookback_from": lookback_from,
        "lookback_to": lookback_to_exclusive - timedelta(days=1),
        "lookback_years": 3,
        "basis": "three_prior_calendar_years",
        "first_observed_company_count": counts["first_observed"],
        "reentering_company_count": counts["reentering"],
        "incumbent_company_count": counts["incumbent"],
        "total_company_count": total,
        "first_observed_company_rate": (
            round(counts["first_observed"] / total, 6) if total else None
        ),
        "reentering_company_rate": (
            round(counts["reentering"] / total, 6) if total else None
        ),
        "entry_and_reentry_company_count": entry_count,
        "entry_and_reentry_rate": round(entry_count / total, 6) if total else None,
        "history_available_from": history_available_from,
        "history_complete_for_lookback": history_complete,
        "history_complete_for_first_observed": False,
        "minimum_sample_size": 10,
        "sample_sufficient": total >= 10,
        "company_preview": [
            item for item in companies if item["entry_status"] != "incumbent"
        ][:5],
    }
    return summary, companies


def _contract_method_group(value: Any) -> tuple[str, str]:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return "unknown", "미분류"
    if "수의" in normalized:
        return "direct", "수의계약"
    if any(label in normalized for label in ("일반경쟁", "제한경쟁", "지명경쟁")):
        return "competitive", "경쟁계약"
    return "other", "기타"


def _organization_market_structure(
    profile_rows: list[dict[str, Any]], relationships: list[dict[str, Any]],
    *, notice_rows: list[dict[str, Any]], period_to: date,
    rolling_12m: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    contract_rows = [row for row in profile_rows if row.get("activity_type") == "contract"]

    notices: dict[str, date] = {}
    for row in notice_rows:
        published = row.get("notice_published_date")
        notice_id = str(row.get("bid_notice_id") or "")
        if published and notice_id and not notice_id.startswith("contract:"):
            notices[notice_id] = published
    quarter_counts = {quarter: 0 for quarter in range(1, 5)}
    for published in notices.values():
        quarter_counts[(published.month - 1) // 3 + 1] += 1
    notice_total = len(notices)
    quarter_distribution = [{
        "quarter": quarter,
        "notice_count": count,
        "notice_share": round(count / notice_total, 6) if notice_total else None,
    } for quarter, count in quarter_counts.items()]

    method_events: dict[str, dict[str, Any]] = {}
    for row in contract_rows:
        event_key = str(row.get("event_key") or "")
        event = method_events.setdefault(event_key, {
            "methods": set(), "amount": Decimal("0"), "has_amount": False,
        })
        event["methods"].add(_contract_method_group(row.get("contract_method_name"))[0])
        if row.get("attributed_contract_amount") is not None:
            event["amount"] += Decimal(str(row["attributed_contract_amount"]))
            event["has_amount"] = True
    grouped: dict[str, dict[str, Any]] = {}
    labels = {
        "competitive": "경쟁계약", "direct": "수의계약",
        "other": "기타", "unknown": "미분류",
    }
    for event in method_events.values():
        methods = event["methods"]
        method = next(iter(methods)) if len(methods) == 1 else "unknown"
        item = grouped.setdefault(method, {
            "method": method, "method_name": labels[method],
            "contract_event_count": 0, "attributed_contract_amount": Decimal("0"),
        })
        item["contract_event_count"] += 1
        if event["has_amount"]:
            item["attributed_contract_amount"] += event["amount"]
    event_total = len(method_events)
    amount_total = sum(
        (item["attributed_contract_amount"] for item in grouped.values()), Decimal("0")
    )
    method_distribution = []
    for method in ("competitive", "direct", "other", "unknown"):
        item = grouped.get(method, {
            "method": method, "method_name": labels[method],
            "contract_event_count": 0, "attributed_contract_amount": Decimal("0"),
        })
        amount = item["attributed_contract_amount"]
        item["attributed_contract_amount"] = _number(amount)
        item["contract_share"] = (
            round(item["contract_event_count"] / event_total, 6) if event_total else None
        )
        item["amount_share"] = round(float(amount / amount_total), 6) if amount_total else None
        method_distribution.append(item)

    contracted = [item for item in relationships if item.get("contract_event_count", 0) > 0]
    ranked = sorted(
        contracted,
        key=lambda item: item.get("total_attributed_contract_amount") or 0,
        reverse=True,
    )
    top_amount = sum(
        (Decimal(str(item.get("total_attributed_contract_amount") or 0)) for item in ranked[:5]),
        Decimal("0"),
    )
    amount_statuses = [
        str(row.get("amount_completeness") or "unknown") for row in contract_rows
    ]
    completeness = _amount_completeness(amount_statuses)
    excluded_events = len({
        str(row.get("event_key") or "") for row in contract_rows
        if row.get("attributed_contract_amount") is None
    })
    shares = [
        Decimal(str(item.get("total_attributed_contract_amount") or 0)) / amount_total
        for item in contracted
    ] if amount_total else []
    small_population = len(contracted) <= 5
    company_structure = {
        "contracted_company_count": len(contracted),
        "top_5_company_amount": _number(top_amount),
        "total_company_attributed_contract_amount": _number(amount_total),
        "top_5_company_amount_share": (
            round(float(top_amount / amount_total), 6) if amount_total else None
        ),
        "concentration_metric": "cr5",
        "concentration_basis": "attributed_contract_amount",
        "multi_contract_company_count": sum(
            int(item.get("contract_event_count") or 0) >= 2 for item in contracted
        ),
        "single_contract_company_count": sum(
            int(item.get("contract_event_count") or 0) == 1 for item in contracted
        ),
        "amount_completeness": completeness,
        "concentration_computable": bool(amount_total),
        "concentration_note": (
            "contracted_company_count_lte_5" if small_population
            else "contracts_without_attributable_amount_excluded"
            if excluded_events else None
        ),
        "excluded_contract_event_count": excluded_events,
        "small_supplier_population": small_population,
        "hhi": round(float(sum((share * Decimal("100")) ** 2 for share in shares)), 3)
        if shares else None,
        "hhi_scale": "0_to_10000",
        "hhi_basis": "attributed_contract_amount",
        "rolling_12m": rolling_12m,
    }
    return quarter_distribution, method_distribution, company_structure


def _previous_period_comparison(
    rows: list[dict[str, Any]], *, comparison_year: int, current_year: int,
    period_to: date,
) -> dict[str, Any]:
    current_start = date(current_year, 1, 1)
    current_end = period_to if period_to.year == current_year else date(current_year + 1, 1, 1)
    elapsed_end = min(current_end, date(current_year + 1, 1, 1))
    previous_start = date(comparison_year, 1, 1)
    previous_end = _shift_years(elapsed_end, -1)

    def metrics(start: date, end: date) -> tuple[Decimal, int]:
        amounts: dict[str, Decimal] = {}
        events = set()
        for row in rows:
            if row.get("activity_type") != "contract":
                continue
            observed = row.get("activity_date")
            if not observed or not start <= observed < end:
                continue
            event_key = str(row.get("event_key") or "")
            events.add(event_key)
            if row.get("attributed_contract_amount") is not None:
                amounts[event_key] = amounts.get(event_key, Decimal("0")) + Decimal(
                    str(row["attributed_contract_amount"])
                )
        return sum(amounts.values(), Decimal("0")), len(events)

    current_amount, current_count = metrics(current_start, elapsed_end)
    previous_amount, previous_count = metrics(previous_start, previous_end)
    comparable = previous_end > previous_start and previous_amount != 0
    return {
        "basis": "year_over_year",
        "current_year": current_year,
        "comparison_year": comparison_year,
        "contract_amount_change_rate": (
            round(float((current_amount - previous_amount) / previous_amount), 6)
            if comparable else None
        ),
        "contract_event_count_change": current_count - previous_count,
        "comparable": comparable,
        "comparison_note": None if comparable else "previous_period_amount_unavailable",
    }


async def _execute_procurement_profile(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    profile_type: str, reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    (
        period_from, period_to, period_years, period_type,
        period_from_year, period_to_year,
    ) = _resolve_profile_period(inputs, capability_id=capability_id)
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    requested_sort = inputs.get("sort")
    sort_by = str(requested_sort or inputs.get("sort_by", "contract_amount"))
    sort_aliases = {
        "contract_amount_desc": "contract_amount",
        "contract_count_desc": "contract_count",
        "latest_contract_desc": "latest_contract",
    }
    sort_by = sort_aliases.get(sort_by, sort_by)
    if sort_by not in {
        "contract_amount", "contract_count", "award_count", "latest_activity",
        "latest_contract",
    }:
        raise CapabilityExecutionError(
            "invalid_sort_by", f"unsupported sort_by '{sort_by}'",
            capability_id=capability_id,
        )
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    work_type = str(inputs.get("work_type") or "").strip() or None
    company_query = (
        " ".join(str(inputs.get("company_query") or "").split()).casefold()
        if profile_type == "organization" else ""
    )
    organization_query = (
        " ".join(str(inputs.get("organization_query") or "").split()).casefold()
        if profile_type == "company" else ""
    )
    allowed_work_types = {"goods", "service", "construction", "foreign", "other", "unknown"}
    if work_type and work_type not in allowed_work_types:
        raise CapabilityExecutionError(
            "invalid_work_type", f"unsupported work_type '{work_type}'",
            capability_id=capability_id,
        )
    entry_period_to = (
        period_to if period_to < date.today() + timedelta(days=1) else date.today()
    )
    entry_period_from = _shift_years(entry_period_to, -1)
    entry_history_from = date(entry_period_from.year - 5, 1, 1)
    # The rolling supplier metric must use the same contract-version population
    # regardless of the profile's requested start year.  Fetch its full fixed
    # history window before collapsing amended/installment contracts.
    source_period_from = min(period_from, entry_history_from)
    organization_code = (
        str(inputs["organization_code"]) if profile_type == "organization" else None
    )
    organization_company_number = (
        "".join(
            character for character in str(inputs.get("business_registration_number") or "")
            if character.isdigit()
        ) or None
        if profile_type == "organization" else None
    )
    company_number = (
        "".join(character for character in str(inputs["business_registration_number"])
                if character.isdigit()) if profile_type == "company" else None
    )
    resolved_reader = reader or ProcurementProfileReader()
    history_result: tuple[dict[str, date], date | None] | None = None
    notice_rows: list[dict[str, Any]] = []
    try:
        activities_task = asyncio.to_thread(
            resolved_reader.activities, catalog, organization_code=organization_code,
            company_numbers=(
                [company_number] if company_number else
                [organization_company_number] if organization_company_number else []
            ),
            period_from=source_period_from, period_to=period_to,
        )
        history_method = (
            getattr(resolved_reader, "organization_award_history", None)
            if profile_type == "organization" else None
        )
        notice_method = (
            getattr(resolved_reader, "notice_publications", None)
            if profile_type == "organization" else None
        )
        pending = [activities_task]
        if history_method is not None:
            pending.append(asyncio.to_thread(
                    history_method, catalog, organization_code=str(organization_code),
                    history_from=entry_history_from, history_to=period_to,
                    work_type=work_type, large_category=large_category,
                    middle_category=middle_category, field_code=field_code,
                ))
        if notice_method is not None:
            pending.append(asyncio.to_thread(
                notice_method, catalog, organization_code=str(organization_code),
                period_from=period_from, period_to=period_to,
            ))
        gathered = await asyncio.gather(*pending)
        rows = gathered[0]
        offset_result = 1
        if history_method is not None:
            history_result = gathered[offset_result]
            offset_result += 1
        if notice_method is not None:
            notice_rows = gathered[offset_result]
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    rows = _filter_profile_rows(
        rows, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    notice_rows = _filter_profile_rows(
        notice_rows, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    rows = _collapse_profile_contract_versions(rows)
    missing_first_contract_date_count = len({
        str(row.get("event_key") or row.get("bid_notice_id") or "")
        for row in rows
        if row.get("activity_type") == "contract"
        and row.get("first_contract_date") is None
    } - {""})
    profile_rows = [
        row for row in rows if row.get("activity_date") and row["activity_date"] >= period_from
    ]
    incumbent_share = None
    supplier_entry = None
    supplier_entry_companies: list[dict[str, Any]] = []
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
            target_year = (period_to - timedelta(days=1)).year
            supplier_history_rows = [
                row for row in rows
                if row.get("activity_date") and row["activity_date"] >= entry_history_from
            ]
            supplier_entry, supplier_entry_companies = _supplier_entry(
                supplier_history_rows, target_year=target_year, period_to=period_to,
                history_available_from=history_from,
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
            require_contract_relationship=profile_type == "organization",
            notice_rows=notice_rows if profile_type == "organization" else None,
            period_from=period_from, period_to=period_to,
        )
    )
    if profile_type == "organization":
        summary["company_count_basis"] = "contracted_companies"
    summary["missing_first_contract_date_count"] = missing_first_contract_date_count
    if incumbent_share is not None:
        summary["rolling_12m_supplier_entry"] = incumbent_share
    if supplier_entry is not None:
        summary["supplier_entry"] = supplier_entry
    notice_quarter_distribution = None
    contract_method_distribution = None
    company_structure = None
    previous_period_comparison = None
    if profile_type == "organization":
        contract_count = int(summary.get("contract_event_count") or 0)
        total_amount = summary.get("total_attributed_contract_amount")
        summary["average_contract_amount"] = (
            _number(Decimal(str(total_amount)) / contract_count)
            if total_amount is not None and contract_count else None
        )
        selected_end_year = (period_to - timedelta(days=1)).year
        previous_period_comparison = _previous_period_comparison(
            rows, comparison_year=selected_end_year - 1,
            current_year=selected_end_year, period_to=period_to,
        )
        summary["previous_period_comparison"] = previous_period_comparison
        (
            notice_quarter_distribution,
            contract_method_distribution,
            company_structure,
        ) = _organization_market_structure(
            profile_rows, relationships,
            notice_rows=notice_rows or profile_rows, period_to=period_to,
            rolling_12m=incumbent_share,
        )
        summary["notice_quarter_basis_notice_count"] = sum(
            item["notice_count"] for item in notice_quarter_distribution
        )
    field_distribution_level, field_distribution = _drilldown_field_distribution(
        fields, large_category=large_category, middle_category=middle_category,
        field_code=field_code, work_type=work_type,
    )
    field_distribution = decorate_field_distribution(
        field_distribution, level=field_distribution_level, work_type=work_type,
        large_category=large_category, middle_category=middle_category,
    )
    sort_fields = {
        "contract_amount": "total_attributed_contract_amount",
        "contract_count": "contract_event_count",
        "award_count": "award_event_count",
        "latest_activity": "latest_activity_date",
        "latest_contract": "latest_contract_date",
    }
    if company_query:
        relationships = [
            item for item in relationships
            if company_query in " ".join(str(item.get("company_name") or "").split()).casefold()
        ]
    if organization_query:
        relationships = [
            item for item in relationships
            if organization_query in " ".join(
                str(item.get("organization_name") or "").split()
            ).casefold()
        ]
    relationship_key = "company_number" if profile_type == "organization" else "organization_code"
    relationships.sort(key=lambda item: str(item.get(relationship_key) or ""))
    relationships.sort(
        key=lambda item: item.get(sort_fields[sort_by]) or (
            date.min if sort_by in {"latest_activity", "latest_contract"} else 0
        ),
        reverse=True,
    )
    total_items = len(relationships)
    offset = (page - 1) * page_size
    paged = relationships[offset:offset + page_size]
    missing_reasons = []
    if summary["amount_completeness"] != "complete":
        missing_reasons.append("some_contract_amounts_not_attributable")
    if missing_first_contract_date_count:
        missing_reasons.append("some_contract_events_missing_first_contract_date")
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
        "relationship_count": (
            summary["company_count"] if profile_type == "organization" else total_items
        ),
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
            "sort": {
                "contract_amount": "contract_amount_desc",
                "contract_count": "contract_count_desc",
                "latest_contract": "latest_contract_desc",
            }.get(sort_by, sort_by),
            "sort_by": sort_by,
        },
        "analysis_basis": {
            "period_from": period_from, "period_to": period_to - timedelta(days=1),
            "period_years": period_years,
            "period_from_year": period_from_year or period_from.year,
            "period_to_year": period_to_year or (period_to - timedelta(days=1)).year,
            "period_type": period_type,
            "amount_basis": "attributed_contract_amount",
            "event_deduplication": "award_contract_linked_and_contract_versions_merged",
            "event_attribution": "contract_first_contract_date",
            "contract_amount_version": "latest_at_or_before_period_end",
            "contract_event_date_basis": "first_contract_date",
            "contract_amount_basis": "latest_version_at_or_before_period_end",
            "contract_amount_year_attribution": "first_contract_year",
            "contract_version_deduplication": "merged_by_contract_event",
            "notice_year_basis": "notice_published_at",
            "award_year_basis": "final_award_date_or_opening_at",
            "contract_year_basis": "first_contract_date",
            "field_filter": {
                "large_category": large_category,
                "middle_category": middle_category,
                "field_code": field_code,
                "field_name": next((
                    identity.get("name") for row in profile_rows
                    if (identity := _procurement_field_identity(row))
                    and field_code and str(identity.get("code") or "") == field_code
                    and identity.get("name")
                ), None),
            },
            "work_type": work_type,
            "company_query": company_query or None,
            "organization_query": organization_query or None,
            "company_relationship_sort": {
                "contract_amount": "contract_amount_desc",
                "contract_count": "contract_count_desc",
                "latest_contract": "latest_contract_desc",
            }.get(sort_by, sort_by),
        },
        "data_completeness": {
            "status": "partial" if missing_reasons else "complete",
            "missing_reasons": missing_reasons,
        },
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    }
    if profile_type == "organization":
        outcome.update({
            "notice_quarter_distribution": notice_quarter_distribution,
            "notice_quarter_basis": "notice_published_at",
            "contract_method_distribution": contract_method_distribution,
            "contract_method_basis": {
                "competitive": ["일반경쟁", "제한경쟁", "지명경쟁"],
                "direct": ["수의계약"],
                "other": [],
                "unknown": ["원천값 없음", "판정 불가"],
            },
            "company_structure": company_structure,
            "supplier_entry": supplier_entry,
            "deprecated_fields": [{
                "field": "rolling_12m_supplier_entry",
                "replacement": "supplier_entry",
            }],
        })
        if inputs.get("_include_supplier_entry_companies"):
            outcome["_supplier_entry_companies"] = supplier_entry_companies
    if profile_type == "company":
        target_year = (period_to - timedelta(days=1)).year
        for relationship in relationships:
            organization_rows = [
                row for row in rows
                if str(row.get("organization_code") or "")
                == str(relationship.get("organization_code") or "")
                and row.get("activity_date") and row["activity_date"] >= entry_history_from
            ]
            entry_summary, entry_companies = _supplier_entry(
                organization_rows, target_year=target_year, period_to=period_to,
                history_available_from=entry_history_from,
            )
            company_entry = entry_companies[0] if entry_companies else None
            relationship["supplier_entry"] = ({
                "target_year": target_year,
                "entry_status": company_entry["entry_status"],
                "entry_status_name": company_entry["entry_status_name"],
                "previous_contract_date": company_entry["previous_contract_date"],
                "history_complete_for_lookback": entry_summary[
                    "history_complete_for_lookback"
                ],
            } if company_entry else None)
        outcome["recent_activity"] = sorted(
            [{
                "bid_notice_id": row["bid_notice_id"], "notice_name": row.get("notice_name"),
                "activity_type": row["activity_type"], "activity_date": row["activity_date"],
                "organization_code": row.get("organization_code"),
                "organization_name": row.get("organization_name"),
                "work_type": row.get("work_type"),
            } for row in profile_rows], key=lambda item: item["activity_date"], reverse=True,
        )[:20]
    elif organization_company_number:
        outcome["_relationship_contract_events"] = sorted(
            [{
                "award_event_id": str(row["event_key"]),
                "bid_notice_id": row.get("bid_notice_id"),
                "notice_linkage": (
                    "linked" if row.get("attribution_date_basis") == "notice_published_at"
                    else "unlinked"
                ),
                "notice_name": row.get("notice_name"),
                "attribution_date": row.get("activity_date"),
                "attribution_date_basis": row.get("attribution_date_basis"),
                "first_contract_date": row.get("first_contract_date"),
                "latest_contract_version_date": row.get("latest_contract_version_date"),
                "contract_date": row.get("latest_contract_version_date"),
                "contract_amount": _number(row.get("event_amount")),
                "attributed_contract_amount": _number(row.get("attributed_contract_amount")),
                "attributed_contract_amount_completeness": row.get("amount_completeness"),
                "work_type": row.get("work_type"),
                "field_code": row.get("procurement_classification_number"),
                "field_name": row.get("procurement_classification_name"),
                "organization_match": True,
            } for row in profile_rows if row.get("activity_type") == "contract"],
            key=lambda item: (
                item.get("attribution_date") or date.min,
                item.get("latest_contract_version_date") or date.min,
                item["award_event_id"],
            ), reverse=True,
        )
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


async def execute_organization_supplier_entry_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    target_year = int(inputs["target_year"])
    status = str(inputs.get("entry_status", "all"))
    if status not in {"all", "first_observed", "reentering", "incumbent"}:
        raise CapabilityExecutionError(
            "invalid_entry_status", f"unsupported entry_status '{status}'",
            capability_id=capability_id,
        )
    sort = str(inputs.get("sort", "contract_amount_desc"))
    if sort not in {
        "contract_amount_desc", "contract_count_desc", "first_contract_desc",
        "company_name_asc",
    }:
        raise CapabilityExecutionError(
            "invalid_sort", f"unsupported sort '{sort}'", capability_id=capability_id,
        )
    profile_inputs = {
        "organization_code": inputs["organization_code"],
        "period_from_year": target_year, "period_to_year": target_year,
        "period_years": 1, "page": 1, "page_size": 1,
        "_include_supplier_entry_companies": True,
    }
    for key in ("work_type", "large_category", "middle_category", "field_code"):
        if inputs.get(key) is not None:
            profile_inputs[key] = inputs[key]
    profile = await _execute_procurement_profile(
        catalog, capability_id, profile_inputs, profile_type="organization", reader=reader,
    )
    outcome = profile.outcome or {}
    supplier_entry = dict(outcome.get("supplier_entry") or {})
    items = list(outcome.pop("_supplier_entry_companies", []))
    if status != "all":
        items = [item for item in items if item["entry_status"] == status]
    if sort == "company_name_asc":
        items.sort(key=lambda item: (str(item.get("company_name") or ""), item["company_number"]))
    else:
        key = {"contract_amount_desc": "target_year_attributed_contract_amount",
               "contract_count_desc": "target_year_contract_count",
               "first_contract_desc": "target_year_first_contract_date"}[sort]
        items.sort(key=lambda item: item.get(key) or 0, reverse=True)
    page, page_size = int(inputs.get("page", 1)), int(inputs.get("page_size", 20))
    total_items = len(items); offset = (page - 1) * page_size
    analysis_basis = {key: supplier_entry.get(key) for key in (
        "target_year", "period_from", "period_to", "lookback_from", "lookback_to",
        "lookback_years", "basis", "history_available_from", "history_complete_for_lookback",
    )}
    analysis_basis.update({key: inputs.get(key) for key in (
        "entry_status", "work_type", "large_category", "middle_category", "field_code",
    )})
    return CapabilityResult(capability_id=capability_id, objects=profile.objects, outcome={
        "organization": outcome.get("organization"), "supplier_entry": supplier_entry,
        "items": items[offset:offset + page_size],
        "pagination": {"page": page, "page_size": page_size, "total_items": total_items,
                       "total_pages": (total_items + page_size - 1) // page_size, "sort": sort},
        "analysis_basis": analysis_basis,
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    })


def _participation_matches_filters(row: dict[str, Any], inputs: dict[str, Any]) -> bool:
    for key in ("work_type", "large_category", "middle_category", "field_code"):
        expected = _normalized_category(inputs.get(key))
        if expected and _normalized_category(row.get(key)) != expected:
            return False
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    if query and query not in " ".join(str(row.get(key) or "") for key in (
        "notice_name", "organization_name", "participant_name", "bid_notice_id",
    )).casefold():
        return False
    return True


async def execute_company_participation_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: CompanyParticipationReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_from, period_to, _, period_type, from_year, to_year = _resolve_profile_period(
        inputs, capability_id=capability_id,
    )
    company_number = "".join(c for c in str(inputs["business_registration_number"]) if c.isdigit())
    try:
        rows = await asyncio.to_thread(
            (reader or CompanyParticipationReader()).find, catalog,
            company_number=company_number, period_from=period_from, period_to=period_to,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    rows = [row for row in rows if _participation_matches_filters(row, inputs)]
    sort = str(inputs.get("sort", "participation_desc"))
    sort_keys = {
        "participation_desc": ("participation_date", True),
        "rank_asc": ("rank", False), "amount_desc": ("bid_amount", True),
    }
    if sort not in sort_keys:
        raise CapabilityExecutionError("invalid_sort", f"unsupported sort '{sort}'", capability_id=capability_id)
    key, reverse = sort_keys[sort]
    rows.sort(key=lambda row: row.get(key) if row.get(key) is not None else (
        date.min if key == "participation_date" else Decimal("Infinity") if not reverse else 0
    ), reverse=reverse)
    items = [{
        "bid_notice_id": row.get("bid_notice_id"), "notice_name": row.get("notice_name"),
        "organization_code": row.get("organization_code"),
        "organization_name": row.get("organization_name"),
        "participation_date": row.get("participation_date"), "rank": row.get("rank"),
        "participant_count": row.get("participant_count"),
        "bid_amount": _number(row.get("bid_amount")),
        "winning_amount": _number(row.get("winning_amount")),
        "result": row.get("result") or "unknown",
        "result_confirmed": bool(row.get("result_confirmed")),
        "work_type": row.get("work_type"), "field_code": row.get("field_code"),
        "field_name": row.get("field_name"), "large_category": row.get("large_category"),
        "middle_category": row.get("middle_category"),
        "classification_source": row.get("classification_source") or "unclassified",
    } for row in rows]
    page, page_size = int(inputs.get("page", 1)), int(inputs.get("page_size", 20))
    total = len(items); offset = (page - 1) * page_size
    return CapabilityResult(capability_id=capability_id, outcome={
        "items": items[offset:offset + page_size],
        "pagination": {"page": page, "page_size": page_size, "total_items": total,
                       "total_pages": (total + page_size - 1) // page_size, "sort": sort},
        "analysis_basis": {"period_from": period_from, "period_to": period_to - timedelta(days=1),
                           "period_from_year": from_year or period_from.year,
                           "period_to_year": to_year or (period_to - timedelta(days=1)).year,
                           "period_type": period_type,
                           **{key: inputs.get(key) for key in ("work_type", "large_category", "middle_category", "field_code")}},
        "data_completeness": {"status": "partial", "missing_reasons": [
            "participants_outside_retained_ranks_not_available"
        ]},
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    })


async def execute_bid_notice_participations(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: BidNoticeParticipationReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"]).strip()
    notice_number, separator, notice_order = bid_notice_id.rpartition(":")
    if not separator or not notice_number or not notice_order:
        raise CapabilityExecutionError(
            "invalid_bid_notice_id", "bid_notice_id must use notice_number:notice_order",
            capability_id=capability_id,
        )
    try:
        rows = await asyncio.to_thread(
            (reader or BidNoticeParticipationReader()).find, catalog,
            notice_number=notice_number, notice_order=notice_order,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc
    if not rows:
        raise CapabilityExecutionError(
            "bid_notice_not_found", f"bid notice '{bid_notice_id}' has no award event",
            capability_id=capability_id,
        )

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("bid_classification_number") or ""),
               str(row.get("rebid_number") or ""))
        event = grouped.setdefault(key, {
            "bid_classification_number": key[0], "rebid_number": key[1],
            "source_participant_count": row.get("source_participant_count"),
            "participants_by_key": {},
        })
        if not row.get("participation_id"):
            continue
        participant_key = str(row.get("business_registration_number") or "").strip()
        if not participant_key:
            participant_key = f"{row.get('participant_name')}:{row.get('opening_rank')}"
        event["participants_by_key"].setdefault(participant_key, {
            "company_name": row.get("participant_name"),
            "business_registration_number": row.get("business_registration_number"),
            "opening_rank": row.get("opening_rank"),
            "bid_amount": _number(row.get("bid_amount")),
            "bid_rate": _number(row.get("bid_rate")),
            "result": row.get("result") or "unknown",
            "result_confirmed": bool(row.get("result_confirmed")),
        })

    opening_events = []
    all_missing_reasons: set[str] = set()
    for event in grouped.values():
        participants = list(event.pop("participants_by_key").values())
        participants.sort(key=lambda item: (
            item["opening_rank"] is None, item["opening_rank"] or 0,
            item.get("company_name") or "",
        ))
        source_count = event["source_participant_count"]
        stored_count = len(participants)
        reasons = []
        if source_count is None:
            status = "unknown"
            reasons.append("source_participant_count_unavailable")
        elif stored_count >= source_count:
            status = "complete"
        else:
            status = "partial"
            reasons.append(
                "participants_outside_top_10_not_retained"
                if source_count > 10 and stored_count >= 10
                else "stored_participant_count_less_than_source_participant_count"
            )
        all_missing_reasons.update(reasons)
        opening_events.append({
            **event, "stored_participant_count": stored_count,
            "returned_participant_count": stored_count,
            "retention_policy": "top_10_plus_winner",
            "participants": participants,
            "data_completeness": {"status": status, "missing_reasons": reasons},
        })
    statuses = {event["data_completeness"]["status"] for event in opening_events}
    overall_status = "partial" if "partial" in statuses else (
        "unknown" if "unknown" in statuses else "complete"
    )
    return CapabilityResult(capability_id=capability_id, outcome={
        "bid_notice_id": bid_notice_id,
        "notice_name": rows[0].get("notice_name"),
        "opening_events": opening_events,
        "data_completeness": {
            "status": overall_status,
            "missing_reasons": sorted(all_missing_reasons),
        },
        "registry_version": catalog.release.version if catalog.release else "unpublished",
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
    })


async def execute_company_competitor_analysis(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: CompanyParticipationReader | None = None,
) -> CapabilityResult:
    period_from, period_to, _, period_type, from_year, to_year = _resolve_profile_period(
        inputs, capability_id=capability_id,
    )
    company_number = "".join(c for c in str(inputs["business_registration_number"]) if c.isdigit())
    try:
        rows = await asyncio.to_thread(
            (reader or CompanyParticipationReader()).competitors, catalog,
            company_number=company_number, period_from=period_from, period_to=period_to,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
                                       source_id="teoria_public_procurement") from exc
    rows = [row for row in rows if _participation_matches_filters(row, inputs)]
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        number = str(row.get("company_number") or "")
        if not number or number == company_number:
            continue
        item = grouped.setdefault(number, {"company_number": number,
            "company_name": row.get("company_name"), "events": set(),
            "latest_co_participation_date": None, "sample_bid_notice_ids": []})
        item["events"].add(str(row.get("participation_event_id")))
        observed = row.get("participation_date")
        if observed and (item["latest_co_participation_date"] is None or observed > item["latest_co_participation_date"]):
            item["latest_co_participation_date"] = observed
        notice_id = row.get("bid_notice_id")
        if notice_id and notice_id not in item["sample_bid_notice_ids"] and len(item["sample_bid_notice_ids"]) < 5:
            item["sample_bid_notice_ids"].append(notice_id)
    items = []
    for item in grouped.values():
        item["co_participation_count"] = len(item.pop("events")); items.append(item)
    items.sort(key=lambda item: (item["co_participation_count"], item["latest_co_participation_date"] or date.min), reverse=True)
    page, page_size = int(inputs.get("page", 1)), int(inputs.get("page_size", 20))
    total = len(items); offset = (page - 1) * page_size
    return CapabilityResult(capability_id=capability_id, outcome={
        "items": items[offset:offset + page_size],
        "pagination": {"page": page, "page_size": page_size, "total_items": total,
                       "total_pages": (total + page_size - 1) // page_size},
        "analysis_basis": {"period_from": period_from, "period_to": period_to - timedelta(days=1),
                           "period_type": period_type, "co_participation_source": "collected_opening_participants",
                           "participant_retention_policy": "top_10_and_award_winners",
                           **{key: inputs.get(key) for key in ("work_type", "large_category", "middle_category", "field_code")}},
        "data_completeness": {"status": "partial", "missing_reasons": [
            "participants_outside_retained_ranks_not_available"
        ]},
    })


def _outcome_contractor(row: dict[str, Any]) -> dict[str, Any]:
    source_role = str(row.get("supplier_role_name") or "").strip()
    joint = bool(row.get("is_joint_contract"))
    role = (
        "sole" if not joint else
        "consortium_lead" if source_role in {"주계약업체", "대표사", "주계약자", "대표업체"}
        else "consortium_member"
    )
    return {
        "business_registration_number": row.get("business_registration_number"),
        "company_name": row.get("supplier_name"),
        "company_role": role,
        "company_role_label": {
            "sole": "단독", "consortium_lead": "대표사", "consortium_member": "구성원",
        }[role],
        "share_percent": _number(row.get("participation_share_rate")),
    }


async def execute_procurement_outcome_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementOutcomeReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_from, period_to, _, period_type, from_year, to_year = _resolve_profile_period(
        inputs, capability_id=capability_id,
    )
    organization_code = str(inputs["organization_code"])
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    sort = str(inputs.get("sort", "latest_activity_desc"))
    if sort != "latest_activity_desc":
        raise CapabilityExecutionError(
            "invalid_sort", f"unsupported sort '{sort}'", capability_id=capability_id,
        )
    work_type = str(inputs.get("work_type") or "").strip() or None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    try:
        award_rows, contract_rows = await asyncio.to_thread(
            (reader or ProcurementOutcomeReader()).find,
            catalog, organization_code=organization_code,
            period_from=period_from, period_to=period_to,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    outcomes: dict[str, dict[str, Any]] = {}
    notice_to_outcome: dict[str, str] = {}
    organization_name = None
    for row in award_rows:
        source_bid_notice_id = str(row["bid_notice_id"])
        outcome_key = str(row.get("notice_lineage_id") or source_bid_notice_id)
        bid_notice_id = str(row.get("representative_bid_notice_id") or source_bid_notice_id)
        notice_to_outcome[source_bid_notice_id] = outcome_key
        organization_name = organization_name or row.get("organization_name")
        item = outcomes.setdefault(outcome_key, {
            "outcome_id": outcome_key, "bid_notice_id": bid_notice_id,
            "notice_lineage_id": outcome_key,
            "root_bid_notice_id": row.get("root_bid_notice_id"),
            "lineage_count": row.get("lineage_count", 1),
            "notice_name": row.get("notice_name"),
            "organization_code": organization_code,
            "organization_name": row.get("organization_name"),
            "awards": [], "contracts": [], "_classification": None,
        })
        award = {
            "award_id": row.get("award_id"),
            "bid_classification_number": row.get("bid_classification_number"),
            "rebid_number": row.get("rebid_number"),
            "award_date": row.get("award_date"),
            "winner_name": row.get("winner_name"),
            "winner_business_registration_number": row.get(
                "winner_business_registration_number"
            ),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        }
        item["awards"].append(award)
        if item["_classification"] is None:
            item["_classification"] = {
                "work_type": row.get("work_type"), "field_code": row.get("field_code"),
                "field_name": row.get("field_name"),
                "large_category": row.get("large_category"),
                "middle_category": row.get("middle_category"),
            }

    contract_versions: dict[str, list[dict[str, Any]]] = {}
    for row in contract_rows:
        contract_versions.setdefault(str(row["contract_event_id"]), []).append(row)
    for contract_event_id, versions in contract_versions.items():
        latest_date = max(
            (row.get("contract_date") for row in versions if row.get("contract_date")),
            default=None,
        )
        latest_versions = [row for row in versions if row.get("contract_date") == latest_date]
        representative = latest_versions[0] if latest_versions else versions[0]
        bid_notice_id = representative.get("bid_notice_id")
        outcome_id = str(
            notice_to_outcome.get(str(bid_notice_id), str(bid_notice_id))
            if bid_notice_id else f"contract:{contract_event_id}"
        )
        organization_name = organization_name or representative.get("organization_name")
        item = outcomes.setdefault(outcome_id, {
            "outcome_id": outcome_id, "bid_notice_id": bid_notice_id,
            "notice_name": representative.get("notice_name"),
            "organization_code": organization_code,
            "organization_name": representative.get("organization_name"),
            "awards": [], "contracts": [], "_classification": None,
        })
        contractors_by_key: dict[str, dict[str, Any]] = {}
        for row in latest_versions:
            contractor = _outcome_contractor(row)
            key = str(
                contractor.get("business_registration_number")
                or f"sequence:{row.get('supplier_sequence')}"
            )
            contractors_by_key[key] = contractor
        contractors = list(contractors_by_key.values())
        lead = next(
            (value for value in contractors if value["company_role"] == "consortium_lead"),
            contractors[0] if len(contractors) == 1 else None,
        )
        contract = {
            "contract_event_id": contract_event_id,
            "unified_contract_number": representative.get("unified_contract_number"),
            "first_contract_date": min(
                row["contract_date"] for row in versions if row.get("contract_date")
            ) if any(row.get("contract_date") for row in versions) else None,
            "contract_date": latest_date,
            "contract_amount": _number(representative.get("contract_amount")),
            "contract_version_count": len({
                row.get("unified_contract_number") for row in versions
            }),
            "lead_contractor": lead, "contractor_count": len(contractors),
            "contractors": contractors,
        }
        item["contracts"].append(contract)
        if not item.get("notice_name"):
            item["notice_name"] = representative.get("notice_name")
        if not item.get("organization_name"):
            item["organization_name"] = representative.get("organization_name")
        if item["_classification"] is None:
            item["_classification"] = {
                "work_type": representative.get("work_type"),
                "field_code": representative.get("field_code"),
                "field_name": representative.get("field_name"),
                "large_category": representative.get("large_category"),
                "middle_category": representative.get("middle_category"),
            }

    filtered = []
    for item in outcomes.values():
        item["awards"].sort(key=lambda value: value.get("award_date") or date.min, reverse=True)
        item["contracts"].sort(
            key=lambda value: value.get("contract_date") or date.min, reverse=True,
        )
        item["award"] = item["awards"][0] if item["awards"] else None
        item["contract"] = item["contracts"][0] if item["contracts"] else None
        item["stage"] = "contract" if item["contract"] else "award"
        item["stage_name"] = "계약" if item["contract"] else "낙찰"
        item["latest_activity_date"] = (
            item["contract"]["contract_date"] if item["contract"]
            else item["award"]["award_date"]
        )
        classification = item.pop("_classification") or {}
        item.update(classification)
        activity_date = item["latest_activity_date"]
        if not activity_date or not period_from <= activity_date < period_to:
            continue
        if work_type and item.get("work_type") != work_type:
            continue
        if large_category and _normalized_category(item.get("large_category")) != large_category:
            continue
        if middle_category and _normalized_category(item.get("middle_category")) != middle_category:
            continue
        if field_code and str(item.get("field_code") or "") != field_code:
            continue
        if query:
            searchable = " ".join(str(value or "") for value in (
                item.get("notice_name"), item.get("bid_notice_id"), item.get("outcome_id"),
                *(award.get("winner_name") for award in item["awards"]),
                *(contractor.get("company_name") for contract in item["contracts"]
                  for contractor in contract["contractors"]),
            )).casefold()
            if query not in searchable:
                continue
        filtered.append(item)
    filtered.sort(
        key=lambda item: (item["latest_activity_date"], item["outcome_id"]), reverse=True,
    )
    total_items = len(filtered)
    offset = (page - 1) * page_size
    page_items = filtered[offset:offset + page_size]
    observed_at = datetime.now(timezone.utc)
    objects = []
    for item in page_items:
        properties = {
            key: item.get(key) for key in (
                "outcome_id", "bid_notice_id", "notice_name", "stage", "latest_activity_date",
            )
        }
        provenance = Provenance(
            kind="execution", source="teoria_runtime",
            operation=f"market_context.{capability_id}",
            mapping="public_procurement_market_context", observed_at=observed_at,
            record_keys=[str(item["outcome_id"])],
        )
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="procurement_outcome",
            object_id=str(item["outcome_id"]), properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    pagination = {
        "page": page, "page_size": page_size, "total_items": total_items,
        "total_pages": (total_items + page_size - 1) // page_size,
    }
    return CapabilityResult(
        capability_id=capability_id, objects=objects, pagination=pagination,
        outcome={
            "organization": {"code": organization_code, "name": organization_name},
            "items": page_items, "pagination": pagination,
            "analysis_basis": {
                "organization_code": organization_code,
                "period_from": period_from, "period_to": period_to - timedelta(days=1),
                "period_from_year": from_year, "period_to_year": to_year,
                "period_type": period_type, "work_type": work_type,
                "field_filter": {
                    "large_category": large_category, "middle_category": middle_category,
                    "field_code": field_code,
                },
                "query": query or None,
                "deduplication": "notice_outcome_with_original_contract_merge",
                "sort": sort,
            },
            "registry_version": catalog.release.version if catalog.release else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
    )


async def execute_procurement_activity_search(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementActivityReader | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    period_from, period_to, _, period_type, from_year, to_year = _resolve_profile_period(
        inputs, capability_id=capability_id,
    )
    organization_code = str(inputs["organization_code"])
    company_number = "".join(
        character for character in str(inputs.get("company_number") or "")
        if character.isdigit()
    ) or None
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    requested_stage = str(inputs.get("stage", "all"))
    sort = str(inputs.get("sort", "latest_activity_desc"))
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    work_type = str(inputs.get("work_type") or "").strip() or None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    field_code = str(inputs.get("field_code") or "").strip() or None
    stage_as_of = datetime.now(timezone.utc)
    try:
        notices, award_rows, contract_rows, participated_notice_ids = await asyncio.to_thread(
            (reader or ProcurementActivityReader()).find, catalog,
            organization_code=organization_code, period_from=period_from,
            period_to=period_to, company_number=company_number,
        )
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error),
        ) from exc

    activities: dict[str, dict[str, Any]] = {}
    notice_to_activity: dict[str, str] = {}
    organization_name = None
    for row in notices:
        activity_id = str(row.get("notice_lineage_id") or row["bid_notice_id"])
        organization_name = organization_name or row.get("organization_name")
        activities[activity_id] = {
            "activity_id": activity_id, "bid_notice_id": str(row["bid_notice_id"]),
            "notice_lineage_id": activity_id,
            "root_bid_notice_id": row.get("root_bid_notice_id"),
            "lineage_count": row.get("lineage_count", 1),
            "notice_name": row.get("notice_name"), "notice_linkage": "linked",
            "organization_code": organization_code,
            "organization_name": row.get("organization_name"),
            "notice": {
                "published_at": row.get("published_at"),
                "bid_begin_at": row.get("bid_begin_at"),
                "deadline_at": row.get("bid_deadline_at"),
                "status": row.get("bid_status"),
                "notice_status": row.get("notice_status"),
                "allocated_budget": _number(row.get("allocated_budget")),
                "estimated_price": _number(row.get("estimated_price")),
                "base_amount": _number(row.get("base_amount")),
            },
            "awards": [], "contracts": [],
            "work_type": row.get("work_type"), "field_code": row.get("field_code"),
            "field_name": row.get("field_name"),
            "large_category": row.get("large_category"),
            "middle_category": row.get("middle_category"),
            "_notice_status": row.get("notice_status"),
            "_bid_status": row.get("bid_status"),
        }
        notice_to_activity[str(row["bid_notice_id"])] = activity_id
        try:
            lineage_members = json.loads(str(row.get("lineage_notices") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            lineage_members = []
        for member in lineage_members:
            if isinstance(member, dict) and member.get("bid_notice_id"):
                notice_to_activity[str(member["bid_notice_id"])] = activity_id

    participated_activity_ids = {
        notice_to_activity.get(notice_id, notice_id)
        for notice_id in participated_notice_ids
    }

    for row in award_rows:
        activity = activities.get(notice_to_activity.get(
            str(row["bid_notice_id"]), str(row["bid_notice_id"])
        ))
        if activity is None:
            continue
        activity["awards"].append({
            "award_id": row.get("award_id"),
            "bid_classification_number": row.get("bid_classification_number"),
            "rebid_number": row.get("rebid_number"),
            "award_date": row.get("award_date"), "winner_name": row.get("winner_name"),
            "winner_business_registration_number": row.get(
                "winner_business_registration_number"
            ),
            "winning_amount": _number(row.get("winning_amount")),
            "winning_rate": _number(row.get("winning_rate")),
        })

    contract_versions: dict[str, list[dict[str, Any]]] = {}
    for row in contract_rows:
        contract_versions.setdefault(str(row["contract_event_id"]), []).append(row)
    for contract_event_id, versions in contract_versions.items():
        dated_versions = [row for row in versions if row.get("contract_date")]
        if not dated_versions:
            continue
        first_contract_date = min(row["contract_date"] for row in dated_versions)
        latest_contract_date = max(row["contract_date"] for row in dated_versions)
        latest_versions = [
            row for row in dated_versions if row["contract_date"] == latest_contract_date
        ]
        representative = latest_versions[0]
        linked_id = str(representative.get("bid_notice_id") or "") or None
        activity = activities.get(notice_to_activity.get(linked_id, linked_id)) if linked_id else None
        if activity is None:
            if linked_id or not period_from <= first_contract_date < period_to:
                continue
            activity_id = f"contract:{contract_event_id}"
            organization_name = organization_name or representative.get("organization_name")
            activity = activities.setdefault(activity_id, {
                "activity_id": activity_id, "bid_notice_id": None,
                "notice_name": representative.get("notice_name"),
                "notice_linkage": "unlinked", "organization_code": organization_code,
                "organization_name": representative.get("organization_name"),
                "notice": None, "awards": [], "contracts": [],
                "work_type": representative.get("work_type"),
                "field_code": representative.get("field_code"),
                "field_name": representative.get("field_name"),
                "large_category": representative.get("large_category"),
                "middle_category": representative.get("middle_category"),
                "_notice_status": None, "_bid_status": None,
            })
        contractors_by_key: dict[str, dict[str, Any]] = {}
        for row in latest_versions:
            contractor = _outcome_contractor(row)
            key = str(
                contractor.get("business_registration_number")
                or f"sequence:{row.get('supplier_sequence')}"
            )
            contractors_by_key[key] = contractor
        contractors = list(contractors_by_key.values())
        lead = next(
            (value for value in contractors if value["company_role"] == "consortium_lead"),
            contractors[0] if len(contractors) == 1 else None,
        )
        activity["contracts"].append({
            "contract_event_id": contract_event_id,
            "unified_contract_number": representative.get("unified_contract_number"),
            "first_contract_date": first_contract_date,
            "contract_date": latest_contract_date,
            "contract_amount": _number(representative.get("contract_amount")),
            "contract_version_count": len({
                row.get("unified_contract_number") for row in versions
            }),
            "lead_contractor": lead, "contractor_count": len(contractors),
            "contractors": contractors,
        })

    filtered_before_stage = []
    for activity in activities.values():
        activity["awards"].sort(
            key=lambda value: value.get("award_date") or date.min, reverse=True,
        )
        activity["contracts"].sort(
            key=lambda value: value.get("contract_date") or date.min, reverse=True,
        )
        activity["award"] = activity["awards"][0] if activity["awards"] else None
        activity["contract"] = activity["contracts"][0] if activity["contracts"] else None
        if activity["notice_linkage"] == "linked":
            notice_amounts = activity["notice"]
            amount_candidates = (
                ("allocated_budget", "배정예산"),
                ("estimated_price", "추정가격"),
                ("base_amount", "기초금액"),
            )
            selected_amount = next((
                (notice_amounts[basis], basis, basis_name)
                for basis, basis_name in amount_candidates
                if notice_amounts.get(basis) is not None
            ), (None, None, None))
        elif activity["contract"] is not None:
            selected_amount = (
                activity["contract"].get("contract_amount"),
                "contract_amount",
                "계약금액",
            )
        else:
            selected_amount = (None, None, None)
        (
            activity["project_amount"], activity["project_amount_basis"],
            activity["project_amount_basis_name"],
        ) = selected_amount
        if activity["contract"]:
            stage = "contract"
            latest_activity_date = activity["contract"]["contract_date"]
        elif activity["award"]:
            stage = "award"
            latest_activity_date = activity["award"]["award_date"]
        elif activity.pop("_notice_status") == "cancelled":
            stage = "failed_or_cancelled"
            latest_activity_date = activity["notice"]["published_at"]
        else:
            activity.pop("_bid_status")
            published_at = activity["notice"]["published_at"]
            deadline_at = activity["notice"]["deadline_at"]
            published_moment = (
                published_at if isinstance(published_at, datetime)
                else datetime.combine(published_at, datetime.min.time(), timezone.utc)
            )
            if published_moment.tzinfo is None:
                published_moment = published_moment.replace(tzinfo=timezone.utc)
            deadline_moment = None
            if deadline_at is not None:
                deadline_moment = (
                    deadline_at if isinstance(deadline_at, datetime)
                    else datetime.combine(deadline_at, datetime.min.time(), timezone.utc)
                )
                if deadline_moment.tzinfo is None:
                    deadline_moment = deadline_moment.replace(tzinfo=timezone.utc)
            stage = (
                "scheduled" if published_moment > stage_as_of else
                "open" if deadline_moment is not None and stage_as_of < deadline_moment else
                "closed"
            )
            latest_activity_date = published_at
        activity.pop("_notice_status", None)
        activity.pop("_bid_status", None)
        activity["stage"] = stage
        activity["stage_name"] = {
            "scheduled": "예정", "open": "진행", "closed": "마감",
            "award": "낙찰", "contract": "계약",
            "failed_or_cancelled": "유찰·취소",
        }[stage]
        activity["latest_activity_date"] = (
            latest_activity_date.date()
            if isinstance(latest_activity_date, datetime) else latest_activity_date
        )
        if work_type and activity.get("work_type") != work_type:
            continue
        if large_category and _normalized_category(activity.get("large_category")) != large_category:
            continue
        if middle_category and _normalized_category(activity.get("middle_category")) != middle_category:
            continue
        if field_code and str(activity.get("field_code") or "") != field_code:
            continue
        if company_number:
            matched_company = activity.get("activity_id") in participated_activity_ids
            matched_company = matched_company or any(
                award.get("winner_business_registration_number") == company_number
                for award in activity["awards"]
            ) or any(
                contractor.get("business_registration_number") == company_number
                for contract in activity["contracts"]
                for contractor in contract["contractors"]
            )
            if not matched_company:
                continue
        if query:
            searchable = " ".join(str(value or "") for value in (
                activity.get("notice_name"), activity.get("bid_notice_id"),
                activity.get("activity_id"),
                *(award.get("winner_name") for award in activity["awards"]),
                *(contractor.get("company_name") for contract in activity["contracts"]
                  for contractor in contract["contractors"]),
            )).casefold()
            if query not in searchable:
                continue
        filtered_before_stage.append(activity)

    stage_counts = {
        value: sum(item["stage"] == value for item in filtered_before_stage)
        for value in (
            "scheduled", "open", "closed", "award", "contract", "failed_or_cancelled",
        )
    }
    stage_counts["all"] = len(filtered_before_stage)
    linkage_counts = {
        "linked": sum(
            item["notice_linkage"] == "linked" for item in filtered_before_stage
        ),
        "unlinked": sum(
            item["notice_linkage"] == "unlinked" for item in filtered_before_stage
        ),
    }
    filtered = (
        filtered_before_stage if requested_stage == "all"
        else [item for item in filtered_before_stage if item["stage"] == requested_stage]
    )
    filtered.sort(
        key=lambda item: (item["latest_activity_date"], item["activity_id"]), reverse=True,
    )
    total_items = len(filtered)
    offset = (page - 1) * page_size
    page_items = filtered[offset:offset + page_size]
    pagination = {
        "page": page, "page_size": page_size, "total_items": total_items,
        "total_pages": (total_items + page_size - 1) // page_size,
    }
    observed_at = datetime.now(timezone.utc)
    objects = []
    for item in page_items:
        properties = {key: item.get(key) for key in (
            "activity_id", "bid_notice_id", "notice_name", "stage", "latest_activity_date",
            "project_amount", "project_amount_basis", "project_amount_basis_name",
        )}
        provenance = Provenance(
            kind="execution", source="teoria_runtime",
            operation=f"market_context.{capability_id}",
            mapping="public_procurement_market_context", observed_at=observed_at,
            record_keys=[str(item["activity_id"])],
        )
        objects.append(MaterializedObject(
            ontology="public_procurement", object_type="procurement_activity",
            object_id=str(item["activity_id"]), properties=properties,
            provenance=[provenance],
            property_provenance={key: [provenance] for key in properties},
        ))
    return CapabilityResult(
        capability_id=capability_id, objects=objects, pagination=pagination,
        outcome={
            "organization": {"code": organization_code, "name": organization_name},
            "items": page_items, "stage_counts": stage_counts,
            "linkage_counts": linkage_counts, "pagination": pagination,
            "analysis_basis": {
                "period_from": period_from, "period_to": period_to - timedelta(days=1),
                "period_from_year": from_year, "period_to_year": to_year,
                "period_type": period_type,
                "period_basis": "notice_published_at",
                "linked_activity_period_basis": "notice_published_at",
                "unlinked_contract_period_basis": "first_contract_date",
                "sort_basis": "latest_activity_date", "sort": sort,
                "stage_as_of": stage_as_of,
                "stage_policy": "publication_to_deadline",
                "bid_begin_at_used_for_stage": False,
                "company_number": company_number,
                "company_filter_basis": (
                    ["opening_top10_participation", "award_winner", "contract_supplier"]
                    if company_number else []
                ),
                "participation_completeness": "partial" if company_number else None,
                "work_type": work_type,
                "field_filter": {
                    "large_category": large_category, "middle_category": middle_category,
                    "field_code": field_code,
                },
                "query": query or None, "stage": requested_stage,
                "deduplication": "notice_lifecycle_with_original_contract_merge",
            },
            "registry_version": catalog.release.version if catalog.release else "unpublished",
            "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3)},
        },
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


def _representative_notice_amount(row: dict[str, Any]) -> tuple[Any, str | None]:
    for field in ("allocated_budget", "estimated_price", "base_amount"):
        if row.get(field) is not None:
            return row[field], field
    return None, None


def _midrank_percentile(value: float, population: list[float]) -> float | None:
    if not population:
        return None
    lower = sum(item < value for item in population)
    equal = sum(item == value for item in population)
    return round((lower + (equal * 0.5)) / len(population), 6)


def _distribution(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    ordered = sorted(values)
    quantiles = statistics.quantiles(ordered, n=4, method="inclusive") if len(ordered) > 1 else [ordered[0]] * 3
    return round(float(statistics.median(ordered)), 6), round(float(quantiles[0]), 6), round(float(quantiles[2]), 6)


def _build_peer_benchmark(
    contract_rows: list[dict[str, Any]], competition_rows: list[dict[str, Any]], *,
    current_organization_code: str, period_from: date, cutoff: date,
    filters: dict[str, Any],
) -> dict[str, Any]:
    policy = {"minimum_contract_event_count": 10, "minimum_company_count": 5,
              "minimum_competition_bid_count": 5,
              "new_supplier_lookback_years": 3,
              "percentile_method": "midrank"}
    current_contracts = [row for row in contract_rows if period_from <= row["first_contract_date"] < cutoff]
    by_org: dict[str, list[dict[str, Any]]] = {}
    history: dict[tuple[str, str], list[date]] = {}
    for row in contract_rows:
        organization = str(row.get("organization_code") or "")
        company = str(row.get("company_number") or "")
        if organization and company:
            history.setdefault((organization, company), []).append(row["first_contract_date"])
    for row in current_contracts:
        by_org.setdefault(str(row["organization_code"]), []).append(row)

    metrics: dict[str, dict[str, Any]] = {}
    for organization, rows in by_org.items():
        event_keys = {str(row["event_key"]) for row in rows}
        company_amounts: dict[str, Decimal] = {}
        eligible_total = Decimal("0")
        new_amount = Decimal("0")
        companies = {str(row["company_number"]) for row in rows}
        new_companies: set[str] = set()
        excluded = 0
        for row in rows:
            amount = row.get("attributed_contract_amount")
            company = str(row["company_number"])
            event_date = row["first_contract_date"]
            lookback = date(event_date.year - 3, 1, 1)
            was_new = not any(
                lookback <= value < date(event_date.year, 1, 1)
                for value in history[(organization, company)]
            )
            if was_new:
                new_companies.add(company)
            if amount is None:
                excluded += 1
                continue
            numeric = Decimal(str(amount)); eligible_total += numeric
            company_amounts[company] = company_amounts.get(company, Decimal("0")) + numeric
            if was_new:
                new_amount += numeric
        ranked = sorted(company_amounts.values(), reverse=True)
        shares = [float(value / eligible_total) for value in ranked] if eligible_total else []
        metrics[organization] = {
            "contract_event_count": len(event_keys), "company_count": len(companies),
            "cr1": sum(shares[:1]), "cr3": sum(shares[:3]), "cr5": sum(shares[:5]),
            "hhi": sum((share * 100) ** 2 for share in shares),
            "new_supplier_amount_share": float(new_amount / eligible_total) if eligible_total else None,
            "new_supplier_company_share": len(new_companies) / len(companies) if companies else None,
            "new_supplier_contract_amount": _number(new_amount),
            "total_eligible_contract_amount": _number(eligible_total),
            "new_supplier_company_count": len(new_companies), "excluded_amount_count": excluded,
        }
    competition_by_org: dict[str, list[int]] = {}
    competition_source_counts: dict[str, int] = {}
    for row in competition_rows:
        organization = str(row.get("organization_code") or "")
        competition_source_counts[organization] = competition_source_counts.get(organization, 0) + 1
        if row.get("participant_count") is not None:
            competition_by_org.setdefault(organization, []).append(int(row["participant_count"]))
    for organization, values in competition_by_org.items():
        metrics.setdefault(organization, {})["participant_median"] = float(statistics.median(values))
        metrics[organization]["participant_average"] = float(statistics.mean(values))
        metrics[organization]["single_participant_share"] = sum(value == 1 for value in values) / len(values)
        metrics[organization]["competition_bid_count"] = len(values)
        metrics[organization]["excluded_bid_count"] = competition_source_counts[organization] - len(values)

    eligible_contract = {key: value for key, value in metrics.items()
        if value.get("contract_event_count", 0) >= 10 and value.get("company_count", 0) >= 5
        and value.get("total_eligible_contract_amount")}
    eligible_competition = {key: value for key, value in metrics.items()
        if value.get("competition_bid_count", 0) >= 5}
    current = metrics.get(current_organization_code, {})

    def comparison(metric: str, population: dict[str, dict[str, Any]], direction: str) -> dict[str, Any]:
        value = current.get(metric)
        values = [float(item[metric]) for key, item in population.items()
            if key != current_organization_code and item.get(metric) is not None]
        median, p25, p75 = _distribution(values)
        return {"status": "available" if value is not None and values else "unavailable",
                "current_value": round(float(value), 6) if value is not None else None,
                "peer_median": median, "peer_p25": p25, "peer_p75": p75,
                "percentile": _midrank_percentile(float(value), values) if value is not None else None,
                "percentile_method": "midrank", "direction": direction,
                "peer_organization_count": len(values)}

    concentration = comparison("cr5", eligible_contract, "higher_means_more_concentrated")
    concentration.update({"metric": "contract_amount_cr5",
        "current_contract_event_count": current.get("contract_event_count", 0),
        "current_company_count": current.get("company_count", 0),
        "minimum_sample_satisfied": current_organization_code in eligible_contract,
        "completeness": "partial" if current.get("excluded_amount_count") else "complete"})
    new_share = comparison("new_supplier_amount_share", eligible_contract,
        "higher_means_more_amount_awarded_to_entry_or_reentering_suppliers")
    new_share.update({"new_supplier_contract_amount": current.get("new_supplier_contract_amount"),
        "total_eligible_contract_amount": current.get("total_eligible_contract_amount"),
        "new_supplier_company_count": current.get("new_supplier_company_count", 0),
        "contracted_company_count": current.get("company_count", 0),
        "company_share": current.get("new_supplier_company_share"),
        "minimum_sample_satisfied": current_organization_code in eligible_contract,
        "completeness": "partial" if current.get("excluded_amount_count") else "complete"})
    participant = comparison("participant_median", eligible_competition, "higher_means_more_participants")
    participant["average"] = current.get("participant_average")
    single = comparison("single_participant_share", eligible_competition,
        "higher_means_more_single_participant_bids")
    competition = {"status": "available" if participant["status"] == "available" else "unavailable",
        "participant_count_median": participant, "single_participant_share": single,
        "current_bid_count": current.get("competition_bid_count", 0),
        "excluded_bid_count": current.get("excluded_bid_count", 0),
        "minimum_sample_satisfied": current_organization_code in eligible_competition,
        "completeness": "partial" if current.get("excluded_bid_count") else "complete"}
    for section in (concentration, new_share, competition):
        section["interpretation_allowed"] = bool(section.get("minimum_sample_satisfied") and section.get("status") == "available")
        section["interpretation_reason"] = None if section["interpretation_allowed"] else "minimum_sample_not_satisfied"
        section["benchmark_available"] = section.get("status") == "available"
    return {"status": "available" if eligible_contract or eligible_competition else "unavailable",
        "comparison_unit": "organization_official_field", "field_filter": filters,
        "period_from": period_from, "period_to": cutoff - timedelta(days=1),
        "peer_organization_count": len(set(eligible_contract) | set(eligible_competition)),
        "policy": policy, "supplier_concentration": concentration,
        "new_supplier_amount_share": new_share, "competition": competition}


async def execute_bid_participation_context(
    catalog: RegistryCatalog, capability_id: str, inputs: dict[str, Any], *,
    reader: ProcurementProfileReader | None = None, cache: Any | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 3))
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_inputs = {"bid_notice_id": bid_notice_id, "period_years": period_years,
                    "processor_version": "1.1.11"}
    cache_key = cache.key(registry_version, capability_id, cache_inputs) if cache is not None else (
        bid_notice_id, period_years, registry_version)
    shared_cached = await cache.get(cache_key) if cache is not None and reader is None else None
    cached = _BID_PARTICIPATION_CONTEXT_CACHE.get(cache_key) if cache is None and reader is None else None
    if shared_cached is not None or (cached and time.monotonic() - cached[0] < 600):
        result = shared_cached or cached[1].model_copy(deep=True)
        result.outcome["timings"] = {
            "total_ms": round((time.perf_counter() - started) * 1000, 3), "cache_hit": True,
        }
        return result
    resolved_reader = reader or ProcurementProfileReader()
    try:
        notice, _ = await asyncio.to_thread(
            resolved_reader.bid_context, catalog, bid_notice_id=bid_notice_id,
        )
        cutoff = notice["notice_published_date"]
        period_from = _shift_years(cutoff, -period_years)
        history_from = date(cutoff.year - 3, 1, 1)
        organization_code = str(notice.get("organization_code") or "")
        if not organization_code:
            raise ValueError(f"bid notice '{bid_notice_id}' has no demand organization code")
        work_type = str(notice.get("work_type") or "unknown")
        filters = {
            "work_type": work_type,
            "large_category": _normalized_category(notice.get("large_category")),
            "middle_category": _normalized_category(notice.get("middle_category")),
            "field_code": str(notice.get("field_code") or "").strip() or None,
        }
        peer_loader = getattr(resolved_reader, "peer_field_market", None)
        peer_task = (asyncio.to_thread(peer_loader, catalog,
            period_from=period_from, period_to=cutoff,
            history_from=date(period_from.year - 3, 1, 1), **filters)
            if peer_loader else asyncio.sleep(0, result=([], [])))
        rows, notices, competition_rows, peer_data = await asyncio.gather(
            asyncio.to_thread(resolved_reader.activities, catalog,
                organization_code=organization_code, company_numbers=[],
                period_from=min(period_from, history_from), period_to=cutoff),
            asyncio.to_thread(resolved_reader.notice_publications, catalog,
                organization_code=organization_code, period_from=period_from, period_to=cutoff),
            asyncio.to_thread(resolved_reader.bid_competition, catalog,
                organization_code=organization_code, period_from=period_from, period_to=cutoff),
            peer_task,
        )
    except LookupError as exc:
        raise CapabilityExecutionError("bid_notice_not_found", str(exc), capability_id=capability_id) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError("database_source_error", str(exc), capability_id=capability_id,
            source_id="teoria_public_procurement", retryable=isinstance(exc, psycopg.Error)) from exc

    peer_contract_rows, peer_competition_rows = peer_data
    rows = _collapse_profile_contract_versions(_filter_profile_rows(rows, **filters))
    period_rows = [row for row in rows if row.get("activity_date") and period_from <= row["activity_date"] < cutoff]
    notices = _filter_profile_rows(notices, **filters)
    competition_rows = _filter_profile_rows(competition_rows, **filters)
    notice_member_to_lineage: dict[str, str] = {}
    for item in notices:
        lineage_id = str(item.get("notice_lineage_id") or item.get("bid_notice_id"))
        notice_member_to_lineage[str(item.get("bid_notice_id"))] = lineage_id
        try:
            members = json.loads(str(item.get("lineage_notices") or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            members = []
        for member in members:
            if isinstance(member, dict) and member.get("bid_notice_id"):
                notice_member_to_lineage[str(member["bid_notice_id"])] = lineage_id
    representative_notices: dict[str, dict[str, Any]] = {}
    for item in notices:
        lineage_id = str(item.get("notice_lineage_id") or item.get("bid_notice_id"))
        current = representative_notices.get(lineage_id)
        if current is None or bool(item.get("is_latest_in_lineage")):
            representative_notices[lineage_id] = item
    notices = list(representative_notices.values())
    representative_competition: dict[str, dict[str, Any]] = {}
    for item in competition_rows:
        lineage_id = str(item.get("notice_lineage_id") or item.get("bid_notice_id"))
        current = representative_competition.get(lineage_id)
        if current is None or bool(item.get("is_latest_in_lineage")):
            representative_competition[lineage_id] = item
    competition_rows = list(representative_competition.values())
    profile_contracts = [row for row in period_rows if row.get("activity_type") == "contract"]
    awards = [row for row in period_rows if row.get("activity_type") == "award"]
    contracts = [{**row, "activity_type": "contract",
        "activity_date": row.get("first_contract_date"),
        "event_amount": row.get("contract_amount"),
        "bid_notice_id": None, "notice_name": row.get("contract_name")}
        for row in peer_contract_rows
        if str(row.get("organization_code")) == organization_code
        and row.get("first_contract_date")
        and period_from <= row["first_contract_date"] < cutoff]

    companies: dict[str, dict[str, Any]] = {}
    event_keys: set[str] = set(); excluded: set[str] = set(); total_amount = Decimal("0")
    for row in contracts:
        number = str(row.get("company_number") or "").strip()
        if not number:
            continue
        item = companies.setdefault(number, {"company_number": number,
            "company_name": row.get("company_name"), "contracts": set(), "awards": set(),
            "amount": Decimal("0"), "dates": [], "years": set(), "statuses": []})
        key = str(row.get("event_key") or ""); item["contracts"].add(key); event_keys.add(key)
        item["dates"].append(row.get("first_contract_date") or row["activity_date"])
        item["years"].add(row["activity_date"].year)
        item["statuses"].append(str(row.get("amount_completeness") or "unknown"))
        amount = row.get("attributed_contract_amount")
        if amount is None:
            excluded.add(key)
        else:
            amount = Decimal(str(amount)); item["amount"] += amount; total_amount += amount
    for row in awards:
        number = str(row.get("company_number") or "")
        if number in companies:
            companies[number]["awards"].add(str(row.get("event_key") or ""))
    ranked = sorted(companies.values(), key=lambda item: (-item["amount"], item["company_number"]))
    def share(size: int) -> float | None:
        if not total_amount: return None
        return round(float(sum((item["amount"] for item in ranked[:size]), Decimal("0")) / total_amount), 6)

    reference_year = cutoff.year; target_from = date(reference_year, 1, 1)
    lookback_from = date(reference_year - 3, 1, 1)
    target_companies = {str(row["company_number"]) for row in rows
        if row.get("activity_type") == "contract" and row.get("company_number")
        and target_from <= row["activity_date"] < cutoff}
    prior_companies = {str(row["company_number"]) for row in rows
        if row.get("activity_type") == "contract" and row.get("company_number")
        and lookback_from <= row["activity_date"] < target_from}
    new_companies = target_companies - prior_companies
    market_entry = {"status": "available" if target_companies else "unavailable",
        "population": "contracted_companies", "reference_year": reference_year,
        "is_year_to_date": True, "period_from": target_from, "period_to": cutoff - timedelta(days=1),
        "lookback_years": 3, "contracted_company_count": len(target_companies),
        "new_supplier_company_count": len(new_companies),
        "new_supplier_rate": round(len(new_companies) / len(target_companies), 6) if target_companies else None,
        "definition": "reference_year_contracted_companies_without_contracts_in_previous_3_fiscal_years",
        "completeness": "complete", "reason": None if target_companies else "no_reference_year_contracts"}

    current_amount, amount_basis = _representative_notice_amount(notice)
    past_amounts = sorted(Decimal(str(value)) for row in notices
        if (value := _representative_notice_amount(row)[0]) is not None)
    project_scale = {"status": "available" if current_amount is not None and past_amounts else "unavailable",
        "current_project_amount": _number(current_amount), "current_project_amount_basis": amount_basis,
        "comparison_event_count": len(past_amounts),
        "median_project_amount": _number(statistics.median(past_amounts)) if past_amounts else None,
        "percentile": round(sum(value <= Decimal(str(current_amount)) for value in past_amounts) / len(past_amounts), 6)
            if current_amount is not None and past_amounts else None,
        "percentile_method": "percent_rank_inclusive",
        "amount_completeness": "complete" if past_amounts else "unknown"}

    participant_counts = [int(row["participant_count"]) for row in competition_rows
        if row.get("participant_count") is not None]
    recent, previous = participant_counts[:5], participant_counts[5:10]
    competition = {"status": "available" if participant_counts else "unavailable",
        "source_bid_count": len(competition_rows),
        "participant_count_available_bid_count": len(participant_counts),
        "excluded_bid_count": len(competition_rows) - len(participant_counts),
        "overall_average_participant_count": round(statistics.mean(participant_counts), 3) if participant_counts else None,
        "overall_median_participant_count": _number(statistics.median(participant_counts)) if participant_counts else None,
        "recent_5_average_participant_count": round(statistics.mean(recent), 3) if recent else None,
        "previous_5_average_participant_count": round(statistics.mean(previous), 3) if previous else None,
        "three_or_fewer_share": round(sum(value <= 3 for value in participant_counts) / len(participant_counts), 6) if participant_counts else None,
        "eight_or_more_share": round(sum(value >= 8 for value in participant_counts) / len(participant_counts), 6) if participant_counts else None,
        "completeness": "complete" if participant_counts and len(participant_counts) == len(competition_rows) else "partial" if participant_counts else "unknown",
        "completeness_reason": None if participant_counts and len(participant_counts) == len(competition_rows)
            else "source_participant_count_missing_for_some_bids"}

    peer_benchmark = _build_peer_benchmark(
        peer_contract_rows, peer_competition_rows,
        current_organization_code=organization_code, period_from=period_from,
        cutoff=cutoff, filters=filters,
    ) if peer_contract_rows or peer_competition_rows else {
        "status": "unavailable", "reason": "peer_market_data_unavailable",
        "interpretation_allowed": False, "benchmark_available": False,
        "minimum_sample_satisfied": False,
    }

    reference_amount = Decimal(str(current_amount)) if current_amount is not None else None
    minimum_amount = reference_amount / Decimal("2") if reference_amount else None
    maximum_amount = reference_amount * Decimal("2") if reference_amount else None
    current_peer_rows = contracts
    peer_history: dict[str, list[date]] = {}
    for row in peer_contract_rows:
        if str(row.get("organization_code")) == organization_code and row.get("company_number"):
            peer_history.setdefault(str(row["company_number"]), []).append(row["first_contract_date"])
    case_candidates = []
    seen_cases: set[tuple[str, str]] = set()
    for row in current_peer_rows:
        amount = row.get("attributed_contract_amount")
        company_number = str(row.get("company_number") or "")
        event_date = row["first_contract_date"]
        key = (str(row.get("event_key")), company_number)
        if key in seen_cases or not company_number or amount is None or reference_amount is None:
            continue
        seen_cases.add(key)
        numeric = Decimal(str(amount))
        if not (minimum_amount <= numeric <= maximum_amount):
            continue
        relationship = _contract_time_relationship(
            event_date, peer_history.get(company_number, []),
        )
        previous_count = relationship["prior_same_organization_field_contract_count"]
        if relationship["contract_time_relationship_status"] != "entry_or_reentering":
            continue
        matched_contract = next((item for item in profile_contracts
            if str(item.get("event_key")) == str(row.get("event_key"))
            and str(item.get("company_number")) == company_number), None)
        linked_bid_notice_id = (matched_contract or {}).get("bid_notice_id")
        if linked_bid_notice_id and str(linked_bid_notice_id).startswith("contract:"):
            linked_bid_notice_id = None
        case_candidates.append({"company_number": company_number,
            "company_name": row.get("company_name"),
            "contract_event_id": row.get("event_key"),
            "unified_contract_number": row.get("unified_contract_number"),
            "contract_name": row.get("contract_name"),
            "latest_contract_version_date": row.get("latest_contract_version_date"),
            "bid_notice_id": linked_bid_notice_id,
            "notice_name": row.get("notice_name") or (matched_contract or {}).get("notice_name") or row.get("contract_name"),
            "organization_code": organization_code,
            "organization_name": notice.get("organization_name"), "work_type": work_type,
            "field_filter": filters, "first_contract_date": event_date,
            "attributed_contract_amount": _number(numeric),
            "current_notice_amount_difference_rate": round(float(abs(numeric-reference_amount)/reference_amount), 6),
            "previous_3_fiscal_year_contract_count": 0,
            "new_supplier_basis": "no_same_organization_field_contract_in_previous_3_fiscal_years",
            "entry_classification": "entry_or_reentering",
            **relationship,
            "amount_completeness": row.get("amount_completeness"),
            "notice_lineage_id": (matched_contract or {}).get("notice_lineage_id") if linked_bid_notice_id else None,
            "notice_linkage": "linked" if linked_bid_notice_id else "unlinked",
            "relationship_context": {"organization_code": organization_code,
                "company_number": company_number, "contract_event_id": row.get("event_key"),
                "period_from_year": period_from.year, "period_to_year": (cutoff-timedelta(days=1)).year,
                **filters}})
    case_candidates.sort(key=lambda item: (item["current_notice_amount_difference_rate"],
        -item["first_contract_date"].toordinal(), -float(item["attributed_contract_amount"])))
    eligible_case_event_ids = {str(item["contract_event_id"]) for item in case_candidates}
    similar_amount_event_ids = {str(row["event_key"]) for row in current_peer_rows
        if reference_amount is not None and row.get("contract_amount") is not None
        and minimum_amount <= Decimal(str(row["contract_amount"])) <= maximum_amount}
    new_supplier_cases = {"status": "available" if reference_amount is not None else "unavailable",
        "reference_amount": _number(reference_amount),
        "amount_range": {"minimum_amount": _number(minimum_amount),
            "maximum_amount": _number(maximum_amount), "rule": "0.5x_to_2.0x",
            "comparison_rule": "candidate_amount_between_0.5x_and_2.0x_reference"},
        "case_unit": "contract_event", "eligible_case_count": len(eligible_case_event_ids),
        "similar_amount_contract_event_count": len(similar_amount_event_ids),
        "excluded_missing_amount_count": sum(row.get("attributed_contract_amount") is None for row in current_peer_rows),
        "completeness": "partial" if any(row.get("attributed_contract_amount") is None for row in current_peer_rows) else "complete",
        "items": case_candidates[:5]}

    attention_suppliers, attention_selection_basis = _build_attention_suppliers(
        current_peer_rows, history=peer_history, cutoff=cutoff,
        period_from=period_from, filters=filters,
        organization_code=organization_code, reference_amount=reference_amount,
    )

    other_field_by_company: dict[str, dict[str, Any]] = {}
    for row in peer_contract_rows:
        number = str(row.get("company_number") or "")
        if not number or not (period_from <= row["first_contract_date"] < cutoff):
            continue
        bucket = other_field_by_company.setdefault(number, {"events": set(), "amount": Decimal("0")})
        if str(row.get("organization_code")) != organization_code:
            bucket["events"].add((str(row.get("organization_code")), str(row.get("event_key"))))
            if row.get("attributed_contract_amount") is not None:
                bucket["amount"] += Decimal(str(row["attributed_contract_amount"]))

    top_suppliers = []
    for rank, item in enumerate(ranked[:5], 1):
        years = sorted(item["years"]); consecutive = 0; expected = years[-1] if years else None
        for year in reversed(years):
            if year != expected: break
            consecutive += 1; expected -= 1
        external = other_field_by_company.get(item["company_number"], {"events": set(), "amount": Decimal("0")})
        similar_count = sum(similar for event, _, similar in [
            (row, False, reference_amount is not None and row.get("attributed_contract_amount") is not None
             and minimum_amount <= Decimal(str(row["attributed_contract_amount"])) <= maximum_amount)
            for row in contracts if str(row.get("company_number")) == item["company_number"]])
        reasons = ["top_contract_amount"]
        if len(item["contracts"]) >= 2: reasons.append("repeated_contracts")
        if item["dates"] and max(item["dates"]) >= cutoff - timedelta(days=365): reasons.append("recent_contract")
        if item["amount"] >= Decimal("1000000000"): reasons.append("large_contract_history")
        if similar_count: reasons.append("similar_amount_experience")
        if any(case["company_number"] == item["company_number"] for case in case_candidates): reasons.append("new_supplier_contract_case")
        if len(item["contracts"]) >= len(external["events"]): reasons.append("organization_specialist")
        if external["events"]: reasons.append("field_specialist")
        reason_values = {
            "top_contract_amount": ("attributed_contract_amount_rank", rank, 5),
            "repeated_contracts": ("same_organization_field_contract_count", len(item["contracts"]), 2),
            "recent_contract": ("days_since_latest_contract", (cutoff-max(item["dates"])).days if item["dates"] else None, 365),
            "large_contract_history": ("same_organization_field_contract_amount", _number(item["amount"]), 1000000000),
            "similar_amount_experience": ("similar_amount_contract_count", similar_count, 1),
            "new_supplier_contract_case": ("new_supplier_case_count", sum(case["company_number"] == item["company_number"] for case in case_candidates), 1),
            "organization_specialist": ("same_organization_field_contract_count", len(item["contracts"]), len(external["events"])),
            "field_specialist": ("other_organization_same_field_contract_count", len(external["events"]), 1),
        }
        attention_evidence = [{"reason": ("entry_or_reentering_contract_case" if reason == "new_supplier_contract_case" else reason),
            "metric": reason_values[reason][0], "value": reason_values[reason][1],
            "threshold": reason_values[reason][2]} for reason in reasons]
        reasons = [("entry_or_reentering_contract_case" if reason == "new_supplier_contract_case" else reason)
            for reason in reasons]
        top_suppliers.append({"company_number": item["company_number"], "company_name": item["company_name"],
            "award_event_count": len(item["awards"]), "contract_event_count": len(item["contracts"]),
            "attributed_contract_amount": _number(item["amount"]),
            "same_organization_field_contract_count": len(item["contracts"]),
            "same_organization_field_contract_amount": _number(item["amount"]),
            "same_organization_other_field_contract_count": None,
            "other_organization_same_field_contract_count": len(external["events"]),
            "other_organization_same_field_contract_amount": _number(external["amount"]),
            "similar_amount_contract_count": similar_count,
            "latest_contract_date": max(item["dates"]) if item["dates"] else None,
            "latest_same_field_contract_date": max(item["dates"]) if item["dates"] else None,
            "active_years": years, "consecutive_active_years": consecutive,
            "entry_classification": "incumbent" if item["company_number"] in prior_companies else "new_supplier",
            "new_supplier_case_count": sum(case["company_number"] == item["company_number"] for case in case_candidates),
            "attention_reasons": reasons, "attention_reason_evidence": attention_evidence,
            "amount_completeness": _amount_completeness(item["statuses"])})

    award_by_notice = {
        notice_member_to_lineage.get(str(row.get("bid_notice_id")), str(row.get("bid_notice_id"))): row
        for row in awards
    }
    contract_by_notice = {
        notice_member_to_lineage.get(str(row.get("bid_notice_id")), str(row.get("bid_notice_id"))): row
        for row in profile_contracts
    }
    related = []
    for row in sorted(notices, key=lambda item: item.get("notice_published_date") or date.min, reverse=True)[:5]:
        notice_id = str(row.get("bid_notice_id"))
        lineage_id = str(row.get("notice_lineage_id") or notice_id)
        award = award_by_notice.get(lineage_id); contract = contract_by_notice.get(lineage_id)
        related.append({"bid_notice_id": notice_id, "notice_name": row.get("notice_name"),
            "notice_kind": row.get("notice_kind"), "notice_lineage_id": lineage_id,
            "lineage_count": row.get("lineage_count", 1),
            "root_bid_notice_id": row.get("root_bid_notice_id") or notice_id,
            "relationship_type": "same_field",
            "matched_factors": ["same_organization", "same_work_type", "same_procurement_field"],
            "notice_published_at": row.get("notice_published_date"),
            "awarded_company_number": award.get("company_number") if award else None,
            "awarded_company_name": award.get("company_name") if award else None,
            "contract_amount": _number(contract.get("event_amount")) if contract else None,
            "contract_date": contract.get("first_contract_date") if contract else None})

    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(kind="execution", source="teoria_runtime",
        operation="market_context.analyze_bid_participation_context",
        mapping="public_procurement_market_context", observed_at=observed_at, record_keys=[bid_notice_id])
    properties = {"bid_participation_context_id": bid_notice_id, "bid_notice_id": bid_notice_id}
    entry_amount = Decimal("0"); incumbent_amount = Decimal("0")
    for row in current_peer_rows:
        amount = row.get("attributed_contract_amount")
        if amount is None or not row.get("company_number"): continue
        event_date = row["first_contract_date"]
        prior_from = date(event_date.year - 3, 1, 1)
        is_entry = not any(prior_from <= value < date(event_date.year, 1, 1)
            for value in peer_history.get(str(row["company_number"]), []))
        if is_entry: entry_amount += Decimal(str(amount))
        else: incumbent_amount += Decimal(str(amount))
    reconciliation = {"contract_event_count": len(event_keys),
        "contracted_company_count": len(companies),
        "total_contract_amount": _number(total_amount),
        "top_supplier_amount_sum": _number(sum((item["amount"] for item in ranked[:5]), Decimal("0"))),
        "new_or_reentering_contract_amount": _number(entry_amount),
        "incumbent_contract_amount": _number(incumbent_amount),
        "excluded_contract_count": len(excluded),
        "amount_difference": _number(total_amount-entry_amount-incumbent_amount)}
    result = CapabilityResult(capability_id=capability_id, objects=[MaterializedObject(
        ontology="public_procurement", object_type="bid_participation_context", object_id=bid_notice_id,
        properties=properties, provenance=[provenance],
        property_provenance={key: [provenance] for key in properties})], outcome={
        "analysis_basis": {"bid_notice_id": bid_notice_id, "notice_published_at": cutoff,
            "period_from": period_from, "period_to": cutoff - timedelta(days=1), "period_years": period_years,
            "organization_code": organization_code, "work_type": work_type, "field_filter": filters,
            "contract_population_basis": {"organization_code": organization_code,
                "work_type": work_type, "field_filter": filters,
                "period_from": period_from, "period_to": cutoff-timedelta(days=1),
                "event_unit": "original_contract_event",
                "version_policy": "latest_version_available_in_ledger",
                "lineage_policy": "one_procurement_project_per_notice_lineage",
                "consortium_attribution_policy": "source_share_else_single_supplier_full_else_unattributed",
                "missing_amount_policy": "excluded"}},
        "market_entry": market_entry,
        "supplier_concentration": {"status": "available" if companies else "unavailable",
            "company_count": len(companies), "contract_event_count": len(event_keys),
            "total_contract_amount": _number(total_amount), "top_1_share": share(1),
            "top_3_share": share(3), "top_5_share": share(5),
            "amount_completeness": "complete" if not excluded else "partial",
            "excluded_contract_count": len(excluded)},
        "project_scale": project_scale, "competition": competition,
        "peer_benchmark": peer_benchmark,
        "new_supplier_similar_amount_cases": new_supplier_cases,
        "reconciliation": reconciliation,
        "attention_suppliers": attention_suppliers,
        "attention_suppliers_selection_basis": attention_selection_basis,
        "selection_basis": {"attention_suppliers": attention_selection_basis},
        "top_suppliers": top_suppliers, "related_past_projects": related,
        "top_suppliers_basis": {"limit": 5, "ranking": "attributed_contract_amount_desc",
            "population": "contracted_companies", "sample_company_count": len(companies),
            "attention_reason_policy": {
                "top_contract_amount": "top_5_attributed_contract_amount_within_population",
                "repeated_contracts": "same_organization_field_contract_count_gte_2",
                "recent_contract": "latest_contract_within_365_days_before_notice",
                "large_contract_history": "same_organization_field_amount_gte_1_billion_krw",
                "similar_amount_experience": "attributed_amount_between_0.5x_and_2.0x_reference",
                "new_supplier_contract_case": "entry_or_reentry_similar_amount_case_exists",
                "organization_specialist": "organization_field_events_gte_other_organization_field_events",
                "field_specialist": "other_organization_same_field_event_exists",
            }},
        "related_past_projects_basis": {"limit": 5,
            "relationship_types_returned": ["same_field"],
            "previous_project_requires_lineage_evidence": True,
            "sample_notice_count": len(notices)},
        "data_completeness": {"status": "partial" if (
            excluded or project_scale["status"] == "unavailable"
            or competition["completeness"] != "complete"
        ) else "complete", "missing_reasons": [reason for condition, reason in (
            (bool(excluded), "some_contract_amounts_not_attributable"),
            (project_scale["status"] == "unavailable", "comparable_notice_amount_unavailable"),
            (competition["completeness"] != "complete", "source_participant_count_missing_for_some_bids"),
            (peer_benchmark.get("status") != "available", "peer_benchmark_unavailable"),
        ) if condition]},
        "registry_version": registry_version,
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 3),
            "cache_hit": False}})
    if reader is None and cache is not None:
        await cache.set(cache_key, result, 600)
    elif reader is None:
        _BID_PARTICIPATION_CONTEXT_CACHE[cache_key] = (time.monotonic(), result.model_copy(deep=True))
    return result


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


def _procurement_field_identity(row: dict[str, Any]) -> dict[str, Any] | None:
    return field_identity(row)


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
                "attribution_date": row.get("attribution_date") or row.get("event_date"),
                "attribution_date_basis": row.get("attribution_date_basis"),
                "awarded_at": row.get("attribution_date") or row.get("event_date"),
                "award_date": row.get("event_date"),
                "contract_date": None,
                "first_contract_date": None,
                "latest_contract_version_date": None,
                "activity_dates": [
                    row.get("attribution_date") or row.get("event_date")
                ] if row.get("attribution_date") or row.get("event_date") else [],
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
        attribution_date = latest.get("attribution_date") or earliest.get("event_date")
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
                "attribution_date": attribution_date,
                "attribution_date_basis": latest.get("attribution_date_basis"),
                "awarded_at": attribution_date,
                "award_date": None,
                "contract_date": latest.get("event_date"),
                "first_contract_date": earliest.get("first_contract_date")
                or earliest.get("event_date"),
                "latest_contract_version_date": latest.get("latest_contract_version_date")
                or latest.get("event_date"),
                "activity_dates": [attribution_date] if attribution_date else [],
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
        event["attribution_date"] = attribution_date
        event["attribution_date_basis"] = latest.get("attribution_date_basis")
        event["contract_date"] = latest.get("event_date")
        event["first_contract_date"] = earliest.get("first_contract_date") or earliest.get(
            "event_date"
        )
        event["latest_contract_version_date"] = latest.get(
            "latest_contract_version_date"
        ) or latest.get("event_date")
        if event.get("notice_published_date") is None:
            event["notice_published_date"] = first.get("notice_published_date")
        event["activity_dates"] = [attribution_date] if attribution_date else []
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
            attributed_at = attribution_date
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
            annualized_at = event.get("attribution_date") or event.get("awarded_at")
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
