from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..related_projects.similarity import number as _number


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


def _distribution(
    values: list[float],
) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    ordered = sorted(values)
    quantiles = (
        statistics.quantiles(ordered, n=4, method="inclusive")
        if len(ordered) > 1
        else [ordered[0]] * 3
    )
    return (
        round(float(statistics.median(ordered)), 6),
        round(float(quantiles[0]), 6),
        round(float(quantiles[2]), 6),
    )


def _build_peer_benchmark(
    contract_rows: list[dict[str, Any]],
    competition_rows: list[dict[str, Any]],
    *,
    current_organization_code: str,
    period_from: date,
    cutoff: date,
    filters: dict[str, Any],
) -> dict[str, Any]:
    policy = {
        "minimum_contract_event_count": 10,
        "minimum_company_count": 5,
        "minimum_competition_bid_count": 5,
        "new_supplier_lookback_years": 3,
        "percentile_method": "midrank",
    }
    current_contracts = [
        row
        for row in contract_rows
        if period_from <= row["first_contract_date"] < cutoff
    ]
    by_org: dict[str, list[dict[str, Any]]] = {}
    history: dict[tuple[str, str], list[date]] = {}
    for row in contract_rows:
        organization = str(row.get("organization_code") or "")
        company = str(row.get("company_number") or "")
        if organization and company:
            history.setdefault((organization, company), []).append(
                row["first_contract_date"]
            )
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
            numeric = Decimal(str(amount))
            eligible_total += numeric
            company_amounts[company] = (
                company_amounts.get(company, Decimal("0")) + numeric
            )
            if was_new:
                new_amount += numeric
        ranked = sorted(company_amounts.values(), reverse=True)
        shares = (
            [float(value / eligible_total) for value in ranked]
            if eligible_total
            else []
        )
        metrics[organization] = {
            "contract_event_count": len(event_keys),
            "company_count": len(companies),
            "cr1": sum(shares[:1]),
            "cr3": sum(shares[:3]),
            "cr5": sum(shares[:5]),
            "hhi": sum((share * 100) ** 2 for share in shares),
            "new_supplier_amount_share": float(new_amount / eligible_total)
            if eligible_total
            else None,
            "new_supplier_company_share": len(new_companies) / len(companies)
            if companies
            else None,
            "new_supplier_contract_amount": _number(new_amount),
            "total_eligible_contract_amount": _number(eligible_total),
            "new_supplier_company_count": len(new_companies),
            "excluded_amount_count": excluded,
        }
    competition_by_org: dict[str, list[int]] = {}
    competition_source_counts: dict[str, int] = {}
    for row in competition_rows:
        organization = str(row.get("organization_code") or "")
        competition_source_counts[organization] = (
            competition_source_counts.get(organization, 0) + 1
        )
        if row.get("participant_count") is not None:
            competition_by_org.setdefault(organization, []).append(
                int(row["participant_count"])
            )
    for organization, values in competition_by_org.items():
        metrics.setdefault(organization, {})["participant_median"] = float(
            statistics.median(values)
        )
        metrics[organization]["participant_average"] = float(statistics.mean(values))
        metrics[organization]["single_participant_share"] = sum(
            value == 1 for value in values
        ) / len(values)
        metrics[organization]["competition_bid_count"] = len(values)
        metrics[organization]["excluded_bid_count"] = competition_source_counts[
            organization
        ] - len(values)

    eligible_contract = {
        key: value
        for key, value in metrics.items()
        if value.get("contract_event_count", 0) >= 10
        and value.get("company_count", 0) >= 5
        and value.get("total_eligible_contract_amount")
    }
    eligible_competition = {
        key: value
        for key, value in metrics.items()
        if value.get("competition_bid_count", 0) >= 5
    }
    current = metrics.get(current_organization_code, {})

    def comparison(
        metric: str, population: dict[str, dict[str, Any]], direction: str
    ) -> dict[str, Any]:
        value = current.get(metric)
        values = [
            float(item[metric])
            for key, item in population.items()
            if key != current_organization_code and item.get(metric) is not None
        ]
        median, p25, p75 = _distribution(values)
        return {
            "status": "available" if value is not None and values else "unavailable",
            "current_value": round(float(value), 6) if value is not None else None,
            "peer_median": median,
            "peer_p25": p25,
            "peer_p75": p75,
            "percentile": _midrank_percentile(float(value), values)
            if value is not None
            else None,
            "percentile_method": "midrank",
            "direction": direction,
            "peer_organization_count": len(values),
        }

    concentration = comparison(
        "cr5", eligible_contract, "higher_means_more_concentrated"
    )
    concentration.update(
        {
            "metric": "contract_amount_cr5",
            "current_contract_event_count": current.get("contract_event_count", 0),
            "current_company_count": current.get("company_count", 0),
            "minimum_sample_satisfied": current_organization_code in eligible_contract,
            "completeness": "partial"
            if current.get("excluded_amount_count")
            else "complete",
        }
    )
    new_share = comparison(
        "new_supplier_amount_share",
        eligible_contract,
        "higher_means_more_amount_awarded_to_entry_or_reentering_suppliers",
    )
    new_share.update(
        {
            "new_supplier_contract_amount": current.get("new_supplier_contract_amount"),
            "total_eligible_contract_amount": current.get(
                "total_eligible_contract_amount"
            ),
            "new_supplier_company_count": current.get("new_supplier_company_count", 0),
            "contracted_company_count": current.get("company_count", 0),
            "company_share": current.get("new_supplier_company_share"),
            "minimum_sample_satisfied": current_organization_code in eligible_contract,
            "completeness": "partial"
            if current.get("excluded_amount_count")
            else "complete",
        }
    )
    participant = comparison(
        "participant_median", eligible_competition, "higher_means_more_participants"
    )
    participant["average"] = current.get("participant_average")
    single = comparison(
        "single_participant_share",
        eligible_competition,
        "higher_means_more_single_participant_bids",
    )
    competition = {
        "status": "available"
        if participant["status"] == "available"
        else "unavailable",
        "participant_count_median": participant,
        "single_participant_share": single,
        "current_bid_count": current.get("competition_bid_count", 0),
        "excluded_bid_count": current.get("excluded_bid_count", 0),
        "minimum_sample_satisfied": current_organization_code in eligible_competition,
        "completeness": "partial" if current.get("excluded_bid_count") else "complete",
    }
    for section in (concentration, new_share, competition):
        section["interpretation_allowed"] = bool(
            section.get("minimum_sample_satisfied")
            and section.get("status") == "available"
        )
        section["interpretation_reason"] = (
            None
            if section["interpretation_allowed"]
            else "minimum_sample_not_satisfied"
        )
        section["benchmark_available"] = section.get("status") == "available"
    return {
        "status": "available"
        if eligible_contract or eligible_competition
        else "unavailable",
        "comparison_unit": "organization_official_field",
        "field_filter": filters,
        "period_from": period_from,
        "period_to": cutoff - timedelta(days=1),
        "peer_organization_count": len(
            set(eligible_contract) | set(eligible_competition)
        ),
        "policy": policy,
        "supplier_concentration": concentration,
        "new_supplier_amount_share": new_share,
        "competition": competition,
    }
