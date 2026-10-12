from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import time
from typing import Any

import psycopg

from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import CapabilityExecutionError, CapabilityResult

from .field_identity import _normalized_category
from .periods import _resolve_profile_period
from .readers import BidNoticeParticipationReader, CompanyParticipationReader
from .related_projects.similarity import number as _number


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
