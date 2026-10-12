from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..periods import _shift_years
from .profile_aggregation import _amount_completeness
from ..related_projects.similarity import number as _number


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
            "target_year_attributed_contract_amount": (
                _number(sum(target_amounts, Decimal("0")))
                if target_amounts else None
            ),
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


def _organization_entry(
    rows: list[dict[str, Any]], *, target_year: int, period_to: date,
    history_available_from: date | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Classify a company's target-year contracting organizations.

    The entry policy is intentionally the same as the organization-to-supplier
    direction: target-year contracts establish the relationship, contracts in
    the three prior calendar years make it incumbent, older observed contracts
    make it reentering, and no earlier observable contract makes it first
    observed.
    """
    projected_rows = []
    for row in rows:
        organization_code = str(row.get("organization_code") or "").strip()
        if row.get("activity_type") != "contract" or not organization_code:
            continue
        projected_rows.append({
            **row,
            "company_number": organization_code,
            "company_name": row.get("organization_name"),
        })
    supplier_summary, supplier_items = _supplier_entry(
        projected_rows,
        target_year=target_year,
        period_to=period_to,
        history_available_from=history_available_from,
    )
    summary = {
        "target_year": supplier_summary["target_year"],
        "period_from": supplier_summary["period_from"],
        "period_to": supplier_summary["period_to"],
        "lookback_from": supplier_summary["lookback_from"],
        "lookback_to": supplier_summary["lookback_to"],
        "lookback_years": supplier_summary["lookback_years"],
        "basis": supplier_summary["basis"],
        "first_observed_organization_count": supplier_summary[
            "first_observed_company_count"
        ],
        "reentering_organization_count": supplier_summary[
            "reentering_company_count"
        ],
        "incumbent_organization_count": supplier_summary[
            "incumbent_company_count"
        ],
        "total_organization_count": supplier_summary["total_company_count"],
        "first_observed_organization_rate": supplier_summary[
            "first_observed_company_rate"
        ],
        "reentering_organization_rate": supplier_summary[
            "reentering_company_rate"
        ],
        "entry_and_reentry_organization_count": supplier_summary[
            "entry_and_reentry_company_count"
        ],
        "entry_and_reentry_rate": supplier_summary["entry_and_reentry_rate"],
        "history_available_from": supplier_summary["history_available_from"],
        "history_complete_for_lookback": supplier_summary[
            "history_complete_for_lookback"
        ],
        "history_complete_for_first_observed": supplier_summary[
            "history_complete_for_first_observed"
        ],
        "minimum_sample_size": supplier_summary["minimum_sample_size"],
        "sample_sufficient": supplier_summary["sample_sufficient"],
    }
    items = [{
        "organization_code": item["company_number"],
        "organization_name": item["company_name"],
        "organization_entry_status": item["entry_status"],
        "organization_entry_status_name": item["entry_status_name"],
        "target_year_contract_count": item["target_year_contract_count"],
        "target_year_attributed_contract_amount": item[
            "target_year_attributed_contract_amount"
        ],
        "amount_completeness": item["amount_completeness"],
        "target_year_first_contract_date": item["target_year_first_contract_date"],
        "target_year_latest_contract_date": item["target_year_latest_contract_date"],
        "first_observed_contract_date": item["first_observed_contract_date"],
        "previous_contract_date": item["previous_contract_date"],
        "reentry_contract_date": item["reentry_contract_date"],
    } for item in supplier_items]
    return summary, items


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
