"""Pure policy for selecting suppliers worth reviewing for a bid.

This module deliberately has no database or Registry dependencies.  The caller
supplies canonical contract rows; this module classifies evidence, preserves the
reason for every decision, and chooses a diverse display list.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AttentionSupplierPolicy:
    limit: int = 5
    per_reason_limit: int = 2
    recent_contract_days: int = 365
    upper_quartile: float = 0.75
    similar_amount_min_factor: Decimal = Decimal("0.5")
    similar_amount_max_factor: Decimal = Decimal("2.0")
    display_reason_limit: int = 2

    @property
    def reason_priority(self) -> tuple[str, ...]:
        return (
            "similar_amount_experience",
            "contract_amount_leader",
            "entry_then_repeat",
            "repeat_contracts",
            "recent_contract",
            "field_upper_quartile_experience",
            "entry_or_reentering_contract",
        )

    @property
    def selection_groups(self) -> tuple[tuple[str, int], ...]:
        return (
            ("similar_amount_experience", self.per_reason_limit),
            ("contract_amount_leader", self.per_reason_limit),
            ("entry_then_repeat", self.per_reason_limit),
            ("repeat_contracts", self.per_reason_limit),
            ("recent_contract", 1),
        )


DEFAULT_ATTENTION_POLICY = AttentionSupplierPolicy()


def json_number(value: Any) -> int | float | None:
    if value is None:
        return None
    numeric = Decimal(str(value))
    return int(numeric) if numeric == numeric.to_integral_value() else float(numeric)


def contract_time_relationship(contract_date: date, prior_dates: list[date]) -> dict[str, Any]:
    """Classify a contract using only history strictly before that contract."""
    history_from = date(contract_date.year - 3, 1, 1)
    prior_count = sum(history_from <= value < contract_date for value in prior_dates)
    status = "repeat" if prior_count else "entry_or_reentering"
    return {
        "contract_time_relationship_status": status,
        "contract_time_relationship_status_name": (
            "반복 계약" if status == "repeat" else "신규·재진입"
        ),
        "prior_same_organization_field_contract_count": prior_count,
        "history_period_from": history_from,
        "history_period_to": contract_date - timedelta(days=1),
        "classification_basis": "history_before_first_contract_date",
    }


def _event(row: dict[str, Any], relationship: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_event_id": str(row["event_key"]),
        "unified_contract_number": row.get("unified_contract_number"),
        "contract_name": row.get("contract_name"),
        "contract_date": row["first_contract_date"],
        "contract_amount": json_number(row.get("contract_amount")),
        "attributed_contract_amount": json_number(row.get("attributed_contract_amount")),
        "contract_time_relationship_status": relationship["contract_time_relationship_status"],
    }


def _entry_then_repeat(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    entries = [event for event in events
        if event["contract_time_relationship_status"] == "entry_or_reentering"]
    for entry in entries:
        repeated = next((event for event in events
            if event["contract_event_id"] != entry["contract_event_id"]
            and event["contract_date"] > entry["contract_date"]
            and event["contract_time_relationship_status"] == "repeat"), None)
        if repeated:
            return {
                "entry_contract_event_id": entry["contract_event_id"],
                "entry_contract_date": entry["contract_date"],
                "repeat_contract_event_id": repeated["contract_event_id"],
                "repeat_contract_date": repeated["contract_date"],
                "days_to_repeat": (repeated["contract_date"] - entry["contract_date"]).days,
            }
    return None


def build_attention_suppliers(
    rows: list[dict[str, Any]], *, history: dict[str, list[date]], cutoff: date,
    period_from: date, filters: dict[str, Any], organization_code: str,
    reference_amount: Decimal | None,
    policy: AttentionSupplierPolicy = DEFAULT_ATTENTION_POLICY,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build an explainable, diverse supplier list from canonical events."""
    event_amounts = {str(row["event_key"]): Decimal(str(row["contract_amount"]))
        for row in rows if row.get("contract_amount") is not None}
    amounts = sorted(event_amounts.values())
    upper_threshold = (Decimal(str(statistics.quantiles(
        amounts, n=4, method="inclusive")[2])) if len(amounts) > 1
        else amounts[0] if amounts else None)

    companies: dict[str, dict[str, Any]] = {}
    for row in rows:
        company_number = str(row.get("company_number") or "")
        if not company_number:
            continue
        relationship = contract_time_relationship(
            row["first_contract_date"], history.get(company_number, []))
        company = companies.setdefault(company_number, {
            "company_number": company_number,
            "company_name": row.get("company_name"),
            "events": {}, "attributed_contract_amount": Decimal("0"),
        })
        company["events"][str(row["event_key"])] = _event(row, relationship)
        if row.get("attributed_contract_amount") is not None:
            company["attributed_contract_amount"] += Decimal(
                str(row["attributed_contract_amount"]))

    amount_leaders = sorted(companies.values(), key=lambda item: (
        -item["attributed_contract_amount"], item["company_number"]))[:2]
    leader_numbers = {item["company_number"] for item in amount_leaders}
    candidates: dict[str, dict[str, Any]] = {}

    for company_number, company in companies.items():
        events = sorted(company["events"].values(), key=lambda item: (
            item["contract_date"], item["contract_event_id"]))
        if not events:
            continue
        reasons: list[str] = []
        evidence: dict[str, Any] = {}

        if company_number in leader_numbers:
            reasons.append("contract_amount_leader")
            evidence["contract_amount_leader"] = {
                "attributed_contract_amount": json_number(company["attributed_contract_amount"]),
                "selection_limit": 2,
            }
        if len(events) >= 2:
            reasons.append("repeat_contracts")
            evidence["repeat_contracts"] = {
                "contract_event_count": len(events),
                "event_ids": [event["contract_event_id"] for event in events],
            }
        upper_events = [event for event in events if upper_threshold is not None
            and event["contract_amount"] is not None
            and Decimal(str(event["contract_amount"])) >= upper_threshold]
        if upper_events:
            reasons.append("field_upper_quartile_experience")
            evidence["field_upper_quartile_experience"] = {
                "percentile": policy.upper_quartile,
                "scope": "same_organization_official_field",
                "meaning": "relative_upper_quartile_not_absolute_large_contract",
                "minimum_contract_amount": json_number(upper_threshold),
                "events": upper_events,
            }
        similar_events = [event for event in events if reference_amount
            and event["contract_amount"] is not None
            and reference_amount * policy.similar_amount_min_factor
                <= Decimal(str(event["contract_amount"]))
                <= reference_amount * policy.similar_amount_max_factor]
        if similar_events:
            reasons.append("similar_amount_experience")
            evidence["similar_amount_experience"] = {
                "reference_amount": json_number(reference_amount),
                "minimum_amount": json_number(reference_amount * policy.similar_amount_min_factor),
                "maximum_amount": json_number(reference_amount * policy.similar_amount_max_factor),
                "rule": "0.5x_to_2.0x", "events": similar_events,
            }
        latest = events[-1]
        if latest["contract_date"] >= cutoff - timedelta(days=policy.recent_contract_days):
            reasons.append("recent_contract")
            evidence["recent_contract"] = {
                "reference_date": cutoff - timedelta(days=1),
                "window_days": policy.recent_contract_days,
                "contract_event_id": latest["contract_event_id"],
                "contract_date": latest["contract_date"],
            }
        entry_events = [event for event in events
            if event["contract_time_relationship_status"] == "entry_or_reentering"]
        if entry_events:
            reasons.append("entry_or_reentering_contract")
            evidence["entry_or_reentering_contract"] = {"events": entry_events}
        transition = _entry_then_repeat(events)
        if transition:
            reasons.append("entry_then_repeat")
            evidence["entry_then_repeat"] = transition

        display_reasons = [reason for reason in policy.reason_priority
            if reason in reasons][:policy.display_reason_limit]
        candidates[company_number] = {
            "company_number": company_number, "company_name": company["company_name"],
            "contract_event_count": len(events),
            "attributed_contract_amount": json_number(company["attributed_contract_amount"]),
            "latest_contract_date": latest["contract_date"],
            "first_contract_date": events[0]["contract_date"],
            "first_contract_status": events[0]["contract_time_relationship_status"],
            "attention_reasons": reasons, "display_attention_reasons": display_reasons,
            "attention_reason_evidence": evidence,
            "relationship_context": {"organization_code": organization_code,
                "company_number": company_number, "period_from_year": period_from.year,
                "period_to_year": (cutoff - timedelta(days=1)).year, **filters},
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for reason, limit in policy.selection_groups:
        pool = [item for item in candidates.values() if reason in item["attention_reasons"]]
        if reason == "entry_then_repeat":
            pool.sort(key=lambda item: (
                item["attention_reason_evidence"][reason]["days_to_repeat"],
                -item["latest_contract_date"].toordinal(), item["company_number"]))
        else:
            pool.sort(key=lambda item: (-len(item["attention_reasons"]),
                -Decimal(str(item["attributed_contract_amount"] or 0)),
                -item["latest_contract_date"].toordinal(), item["company_number"]))
        groups[reason] = pool[:limit]

    selected: dict[str, dict[str, Any]] = {}
    for reason, _ in policy.selection_groups:
        representative = next((item for item in groups[reason]
            if item["company_number"] not in selected), None)
        if representative:
            selected[representative["company_number"]] = representative
        if len(selected) >= policy.limit:
            break
    for offset in range(policy.per_reason_limit):
        for reason, limit in policy.selection_groups:
            pool = groups[reason]
            if offset < min(limit, len(pool)):
                selected.setdefault(pool[offset]["company_number"], pool[offset])
            if len(selected) >= policy.limit:
                break
        if len(selected) >= policy.limit:
            break
    if len(selected) < policy.limit:
        fallback = sorted(candidates.values(), key=lambda item: (
            -len(item["attention_reasons"]),
            -Decimal(str(item["attributed_contract_amount"] or 0)),
            -item["latest_contract_date"].toordinal(), item["company_number"]))
        for item in fallback:
            selected.setdefault(item["company_number"], item)
            if len(selected) >= policy.limit:
                break

    def order(item: dict[str, Any]) -> tuple[Any, ...]:
        primary = min((policy.reason_priority.index(reason)
            for reason in item["attention_reasons"]
            if reason in policy.reason_priority), default=len(policy.reason_priority))
        return (primary, -len(item["attention_reasons"]),
            -Decimal(str(item["attributed_contract_amount"] or 0)),
            -item["latest_contract_date"].toordinal(), item["company_number"])

    basis = {
        "limit": policy.limit,
        "selection_method": "distinct_reason_representatives_then_quota_fill_and_priority_sort",
        "group_limits": dict(policy.selection_groups),
        "sort_priority": list(policy.reason_priority),
        "tie_breakers": ["attention_reason_count_desc", "attributed_contract_amount_desc",
            "latest_contract_date_desc", "company_number_asc"],
        "field_upper_quartile_percentile": policy.upper_quartile,
        "deprecated_attention_reasons": [{"reason": "large_contract_experience",
            "replacement": "field_upper_quartile_experience"}],
        "display_reason_limit": policy.display_reason_limit,
        "recent_contract_window_days": policy.recent_contract_days,
    }
    return sorted(selected.values(), key=order), basis
