from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg

from teoria.domains.public_procurement.market_analysis.relationships.reader import (
    OrganizationFieldEventReader,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..field_identity import _normalized_category
from ..periods import _fiscal_period_start, _resolve_profile_period
from ..profiles.service import _execute_procurement_profile
from ..related_projects.similarity import (
    amount_similarity as _amount_similarity,
)
from ..related_projects.similarity import (
    number as _number,
)
from ..related_projects.similarity import (
    primary_project_type as _primary_project_type,
)
from ..related_projects.similarity import (
    project_type_label as _project_type_label,
)
from ..signal_policy import ORGANIZATION_FIELD_CACHE_TTL_SECONDS
from .organization_metrics import _organization_field_event_analysis


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
        character
        for character in str(inputs["business_registration_number"])
        if character.isdigit()
    )
    field_code = str(inputs["field_code"]) if inputs.get("field_code") else None
    large_category = _normalized_category(inputs.get("large_category"))
    middle_category = _normalized_category(inputs.get("middle_category"))
    procurement_field_code = (
        str(inputs["procurement_field_code"]).strip()
        if inputs.get("procurement_field_code")
        else None
    )
    supported_fields = {
        "information_system": ("정보시스템", "정보시스템 소프트웨어 전산"),
        "security": ("정보보호·보안", "정보보호 보안 방화벽"),
        "communication": ("정보통신·네트워크", "정보통신 통신망 네트워크"),
    }
    if field_code and field_code not in supported_fields:
        raise CapabilityExecutionError(
            "unsupported_field_code",
            f"unsupported field_code '{field_code}'",
            capability_id=capability_id,
        )
    (
        resolved_period_from,
        resolved_period_to,
        period_years,
        resolved_period_type,
        resolved_from_year,
        resolved_to_year,
    ) = _resolve_profile_period(
        {**inputs, "period_years": inputs.get("period_years", 10)},
        capability_id=capability_id,
    )
    page = int(inputs.get("page", 1))
    page_size = int(inputs.get("page_size", 20))
    reference_bid_notice_id = (
        str(inputs["reference_bid_notice_id"])
        if inputs.get("reference_bid_notice_id")
        else None
    )
    work_type = str(inputs["work_type"]) if inputs.get("work_type") else None
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_key = (
        organization_code,
        company_number,
        field_code,
        period_years,
        page,
        page_size,
        reference_bid_notice_id,
        work_type,
        large_category,
        middle_category,
        procurement_field_code,
        registry_version,
        resolved_period_from,
        resolved_period_to,
    )
    shared_cache_key = (
        cache.key(registry_version, capability_id, {"cache_key": cache_key})
        if cache is not None
        else cache_key
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
        context = await resolved_reader.context(
            catalog,
            organization_code=organization_code,
            business_registration_number=company_number,
            reference_bid_notice_id=reference_bid_notice_id,
        )
        reference = context["reference_notice"]
        as_of = (
            reference.get("as_of")
            if reference
            else datetime.combine(resolved_period_to, datetime.min.time(), timezone.utc)
        )
        find_inputs: dict[str, Any] = {
            "organization_code": organization_code,
            "work_type": work_type,
            "as_of": as_of,
        }
        if large_category or middle_category or procurement_field_code:
            find_inputs.update(
                {
                    "large_category": large_category,
                    "middle_category": middle_category,
                    "procurement_field_code": procurement_field_code,
                }
            )
        rows = await resolved_reader.find(catalog, **find_inputs)
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found",
            str(exc),
            capability_id=capability_id,
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc

    if reference:
        analysis_notice = dict(reference)
    else:
        label, synthetic_title = supported_fields.get(field_code, (None, ""))
        analysis_notice = {
            "notice_name": synthetic_title,
            "estimated_price": None,
            "allocated_budget": None,
            "industry_codes": [],
            "as_of": as_of,
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
        if (
            "contract" in event["source_kinds"]
            and attribution_date
            and period_start <= attribution_date < as_of_date
        ):
            contract_event_count += 1
            contract_version_count += len(
                set(
                    event["members"][company_number].get("contract_activity_dates")
                    or []
                )
            )

    project_counts: dict[str, int] = {}
    amount_counts = {"under_1b": 0, "1b_to_3b": 0, "3b_to_10b": 0, "over_10b": 0}
    yearly: dict[int, dict[str, Any]] = {}
    event_items = []
    attributed_event_total = Decimal("0")
    target_amount = analysis_notice.get("estimated_price") or analysis_notice.get(
        "allocated_budget"
    )
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
            "under_1b"
            if amount_number is not None and amount_number < Decimal("1000000000")
            else "1b_to_3b"
            if amount_number is not None and amount_number < Decimal("3000000000")
            else "3b_to_10b"
            if amount_number is not None and amount_number < Decimal("10000000000")
            else "over_10b"
        )
        amount_counts[bucket] += 1
        year = event["awarded_at"].year
        yearly_item = yearly.setdefault(
            year,
            {
                "year": year,
                "event_count": 0,
                "attributed_event_count": Decimal("0"),
                "total_attributed_amount": Decimal("0"),
            },
        )
        yearly_item["event_count"] += 1
        yearly_item["attributed_event_count"] += credit
        if member.get("attributed_amount") is not None:
            yearly_item["total_attributed_amount"] += Decimal(
                str(member["attributed_amount"])
            )
        is_similar = (
            None
            if target_amount is None
            else (_amount_similarity(target_amount, amount)[0] >= 0.5)
        )
        event_items.append(
            {
                "award_event_id": event["event_id"],
                "bid_notice_id": event.get("notice_id"),
                "notice_name": event.get("notice_name"),
                "notice_published_date": event.get("notice_published_date"),
                "attribution_date": event.get("attribution_date"),
                "attribution_date_basis": event.get("attribution_date_basis"),
                "award_date": event.get("award_date"),
                "contract_date": event.get("contract_date"),
                "first_contract_date": event.get("first_contract_date"),
                "latest_contract_version_date": event.get(
                    "latest_contract_version_date"
                ),
                "project_type": project_type,
                "project_type_label": _project_type_label(project_type),
                "award_amount": event.get("award_amount"),
                "contract_amount": event.get("contract_amount"),
                "attributed_contract_amount": member.get("attributed_amount"),
                "attributed_contract_amount_completeness": (
                    "complete"
                    if member.get("attributed_amount") is not None
                    else "partial"
                    if "contract" in event["source_kinds"]
                    else "unknown"
                ),
                "joint_contract": len(members) > 1,
                "company_role": (
                    "sole"
                    if len(members) == 1
                    else "consortium_lead"
                    if member.get("supplier_role_name")
                    in {
                        "대표사",
                        "주계약자",
                        "대표업체",
                    }
                    else "consortium_member"
                ),
                "share_percent": share_percent,
                "share_source": share_source,
                "field_match_reasons": [field_code] if field_code else [],
                "is_similar_amount": is_similar,
                "similar_amount_reason": (
                    None
                    if target_amount is not None
                    else "reference_amount_not_provided"
                ),
            }
        )

    total_items = len(event_items)
    offset = (page - 1) * page_size
    paged_events = event_items[offset : offset + page_size]
    metrics = analysis["company_metrics"].get(company_number, {})
    annual_activity = metrics.get("annual_activity", [])
    annual_completeness = [item["amount_completeness"] for item in annual_activity]
    relationship_amount_completeness = (
        "complete"
        if annual_completeness
        and all(status == "complete" for status in annual_completeness)
        else "unknown"
        if not annual_completeness
        or all(status == "unknown" for status in annual_completeness)
        else "partial"
    )
    total_attributed_contract_amount = sum(
        item["attributed_contract_amount"] for item in annual_activity
    )
    project_order = ["build", "improvement", "maintenance", "consulting", "unknown"]
    project_distribution = [
        {
            "project_type": kind,
            "label": _project_type_label(kind),
            "event_count": project_counts.get(kind, 0),
        }
        for kind in project_order
    ]
    amount_labels = {
        "under_1b": "10억원 미만",
        "1b_to_3b": "10~30억원",
        "3b_to_10b": "30~100억원",
        "over_10b": "100억원 이상",
    }
    amount_distribution = [
        {
            "range": key,
            "label": amount_labels[key],
            "event_count": amount_counts[key],
        }
        for key in amount_labels
    ]
    yearly_activity = [
        {
            **item,
            "attributed_event_count": _number(item["attributed_event_count"]),
            "total_attributed_amount": _number(item["total_attributed_amount"]),
        }
        for _, item in sorted(yearly.items(), reverse=True)
    ]
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution",
        source="teoria_runtime",
        operation="market_context.get_organization_company_field_relationship",
        mapping="public_procurement_market_context",
        observed_at=observed_at,
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
        objects=[
            MaterializedObject(
                ontology="public_procurement",
                object_type="organization_company_field_relationship",
                object_id=properties["organization_company_field_relationship_id"],
                properties=properties,
                provenance=[provenance],
                property_provenance={key: [provenance] for key in properties},
            )
        ],
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
                "period_to_year": resolved_to_year
                or (as_of_date - timedelta(days=1)).year,
                "period_type": resolved_period_type,
                "work_type": work_type,
                "reference_bid_notice_id": reference_bid_notice_id,
                "event_attribution": "notice_published_at_or_first_contract_date",
                "contract_amount_version": "latest_at_or_before_period_end",
                "observation_started_at": analysis["market_entry"][
                    "observation_started_at"
                ],
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
                )
                if target_amount is not None
                else None,
                "total_attributed_contract_amount": total_attributed_contract_amount,
                "amount_completeness": relationship_amount_completeness,
            },
            "project_type_distribution": project_distribution,
            "amount_distribution": amount_distribution,
            "yearly_activity": yearly_activity,
            "annual_activity": annual_activity,
            "events": paged_events,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
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
            time.monotonic(),
            result.model_copy(deep=True),
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
    if inputs.get("view_mode") == "network_edge":
        from teoria.domains.public_procurement.exploration.network import (
            execute_network_organization_company_relationship,
        )

        return await execute_network_organization_company_relationship(
            catalog,
            capability_id,
            inputs,
        )
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
    result.outcome["analysis_basis"].update(
        {
            "field_filter_applied": any(
                inputs.get(key)
                for key in (
                    "large_category",
                    "middle_category",
                    "field_code",
                )
            ),
            "field_filter": {
                "large_category": _normalized_category(inputs.get("large_category")),
                "middle_category": _normalized_category(inputs.get("middle_category")),
                "field_code": str(inputs.get("field_code") or "").strip() or None,
            },
            "similarity_assessment_applied": False,
        }
    )
    result.outcome.pop("field", None)
    result.outcome["yearly_activity"] = result.outcome.pop("annual_activity")
    for event in result.outcome["events"]:
        event["organization_match"] = True
        event.pop("field_match_reasons", None)
    profile = None
    if reader is None:
        profile = await _execute_procurement_profile(
            catalog,
            "analyze_organization_procurement_profile",
            {
                "organization_code": inputs["organization_code"],
                "business_registration_number": inputs["business_registration_number"],
                "period_years": inputs.get("period_years", 10),
                "period_from_year": inputs.get("period_from_year"),
                "period_to_year": inputs.get("period_to_year"),
                "work_type": inputs.get("work_type"),
                "large_category": inputs.get("large_category"),
                "middle_category": inputs.get("middle_category"),
                "field_code": inputs.get("field_code"),
                "page": 1,
                "page_size": 1,
            },
            profile_type="organization",
        )
    relationships = (
        (profile.outcome.get("company_relationships") or []) if profile else []
    )
    relationship = relationships[0] if relationships else None
    if relationship:
        result.outcome["summary"].update(
            {
                key: relationship[key]
                for key in (
                    "award_event_count",
                    "contract_event_count",
                    "contract_version_count",
                    "unique_project_count",
                    "total_attributed_contract_amount",
                    "amount_completeness",
                    "active_years",
                    "active_year_count",
                    "first_activity_date",
                    "latest_activity_date",
                    "latest_contract_date",
                )
            }
        )
        result.outcome["yearly_activity"] = relationship["yearly_activity"]
        result.outcome["major_fields"] = relationship["major_fields"]
        result.outcome["project_type_distribution"] = relationship[
            "project_type_distribution"
        ]
    elif profile is not None:
        result.outcome["summary"].update(
            {
                "award_event_count": 0,
                "contract_event_count": 0,
                "contract_version_count": 0,
                "unique_project_count": 0,
                "total_attributed_contract_amount": 0,
                "amount_completeness": "unknown",
                "active_years": [],
                "active_year_count": 0,
                "first_activity_date": None,
                "latest_activity_date": None,
                "latest_contract_date": None,
            }
        )
        result.outcome["yearly_activity"] = []
        result.outcome["major_fields"] = []
        result.outcome["project_type_distribution"] = []
    if profile is not None:
        result.outcome["analysis_basis"].update(
            {
                key: profile.outcome["analysis_basis"][key]
                for key in (
                    "period_from",
                    "period_to",
                    "period_from_year",
                    "period_to_year",
                    "period_years",
                    "period_type",
                    "event_attribution",
                    "contract_amount_version",
                )
            }
        )
        contract_events = profile.outcome.pop("_relationship_contract_events", [])
        total_events = len(contract_events)
        requested_page = int(inputs.get("page", 1))
        requested_page_size = int(inputs.get("page_size", 20))
        offset = (requested_page - 1) * requested_page_size
        result.outcome["events"] = contract_events[
            offset : offset + requested_page_size
        ]
        result.outcome["pagination"] = {
            "page": requested_page,
            "page_size": requested_page_size,
            "total_items": total_events,
            "total_pages": (total_events + requested_page_size - 1)
            // requested_page_size,
        }
        result.outcome["summary"]["linked_notice_count"] = len(
            {
                item["bid_notice_id"]
                for item in contract_events
                if item.get("bid_notice_id") and item.get("notice_linkage") == "linked"
            }
        )
        result.outcome["summary"]["unlinked_contract_count"] = sum(
            item.get("notice_linkage") == "unlinked" for item in contract_events
        )
    properties = {
        "organization_company_relationship_id": (
            f"{history_inputs['organization_code']}:"
            f"{''.join(character for character in str(history_inputs['business_registration_number']) if character.isdigit())}"
        ),
        "organization_code": history_inputs["organization_code"],
        "company_number": "".join(
            character
            for character in str(history_inputs["business_registration_number"])
            if character.isdigit()
        ),
        "award_event_count": result.outcome["summary"]["award_event_count"],
        "unique_project_count": result.outcome["summary"]["unique_project_count"],
        "contract_event_count": result.outcome["summary"]["contract_event_count"],
        "contract_version_count": result.outcome["summary"]["contract_version_count"],
    }
    provenance = result.objects[0].provenance if result.objects else []
    result.objects = [
        MaterializedObject(
            ontology="public_procurement",
            object_type="organization_company_relationship",
            object_id=properties["organization_company_relationship_id"],
            properties=properties,
            provenance=provenance,
            property_provenance={key: provenance for key in properties},
        )
    ]
    return result


_ORGANIZATION_FIELD_CACHE: dict[
    tuple[str, int, int, str], tuple[float, CapabilityResult]
] = {}


_ORGANIZATION_COMPANY_FIELD_CACHE: dict[
    tuple[Any, ...], tuple[float, CapabilityResult]
] = {}
