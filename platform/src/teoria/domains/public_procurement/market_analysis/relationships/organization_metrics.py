from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..periods import _fiscal_period_start
from ..related_projects.similarity import (
    amount_similarity as _amount_similarity,
    business_fields as _business_fields,
    number as _number,
    project_types as _project_types,
)


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
