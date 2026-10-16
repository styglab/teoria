from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import psycopg

from teoria.domains.public_procurement.market_analysis.profiles.reader import (
    ProcurementProfileReader,
)
from teoria.registry.loader import RegistryCatalog
from teoria.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.runtime.mapping.materializer import MaterializedObject
from teoria.runtime.provenance import Provenance

from ..field_identity import _normalized_category
from ..periods import _shift_years
from ..profiles.profile_aggregation import (
    _amount_completeness,
    _collapse_profile_contract_versions,
    _filter_profile_rows,
)
from ..related_projects.similarity import number as _number
from .peer_benchmark import _build_peer_benchmark, _representative_notice_amount
from .supplier_selection import (
    build_attention_suppliers as _build_attention_suppliers,
)
from .supplier_selection import (
    contract_time_relationship as _contract_time_relationship,
)


async def execute_bid_participation_context(
    catalog: RegistryCatalog,
    capability_id: str,
    inputs: dict[str, Any],
    *,
    reader: ProcurementProfileReader | None = None,
    cache: Any | None = None,
) -> CapabilityResult:
    started = time.perf_counter()
    bid_notice_id = str(inputs["bid_notice_id"])
    period_years = int(inputs.get("period_years", 3))
    registry_version = catalog.release.version if catalog.release else "unpublished"
    cache_inputs = {
        "bid_notice_id": bid_notice_id,
        "period_years": period_years,
        "processor_version": "1.1.11",
    }
    cache_key = (
        cache.key(registry_version, capability_id, cache_inputs)
        if cache is not None
        else (bid_notice_id, period_years, registry_version)
    )
    shared_cached = (
        await cache.get(cache_key) if cache is not None and reader is None else None
    )
    cached = (
        _BID_PARTICIPATION_CONTEXT_CACHE.get(cache_key)
        if cache is None and reader is None
        else None
    )
    if shared_cached is not None or (cached and time.monotonic() - cached[0] < 600):
        result = shared_cached or cached[1].model_copy(deep=True)
        result.outcome["timings"] = {
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
            "cache_hit": True,
        }
        return result
    resolved_reader = reader or ProcurementProfileReader()
    try:
        notice, _ = await resolved_reader.bid_context(
            catalog, bid_notice_id=bid_notice_id
        )
        cutoff = notice["notice_published_date"]
        period_from = _shift_years(cutoff, -period_years)
        history_from = date(cutoff.year - 3, 1, 1)
        organization_code = str(notice.get("organization_code") or "")
        if not organization_code:
            raise ValueError(
                f"bid notice '{bid_notice_id}' has no demand organization code"
            )
        work_type = str(notice.get("work_type") or "unknown")
        filters = {
            "work_type": work_type,
            "large_category": _normalized_category(notice.get("large_category")),
            "middle_category": _normalized_category(notice.get("middle_category")),
            "field_code": str(notice.get("field_code") or "").strip() or None,
        }
        peer_loader = getattr(resolved_reader, "peer_field_market", None)
        peer_task = (
            peer_loader(
                catalog,
                period_from=period_from,
                period_to=cutoff,
                history_from=date(period_from.year - 3, 1, 1),
                **filters,
            )
            if peer_loader
            else asyncio.sleep(0, result=([], []))
        )
        rows, notices, competition_rows, peer_data = await asyncio.gather(
            resolved_reader.activities(
                catalog,
                organization_code=organization_code,
                company_numbers=[],
                period_from=min(period_from, history_from),
                period_to=cutoff,
            ),
            resolved_reader.notice_publications(
                catalog,
                organization_code=organization_code,
                period_from=period_from,
                period_to=cutoff,
            ),
            resolved_reader.bid_competition(
                catalog,
                organization_code=organization_code,
                period_from=period_from,
                period_to=cutoff,
            ),
            peer_task,
        )
    except LookupError as exc:
        raise CapabilityExecutionError(
            "bid_notice_not_found", str(exc), capability_id=capability_id
        ) from exc
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        raise CapabilityExecutionError(
            "database_source_error",
            str(exc),
            capability_id=capability_id,
            source_id="teoria_public_procurement",
            retryable=isinstance(exc, psycopg.Error),
        ) from exc

    peer_contract_rows, peer_competition_rows = peer_data
    rows = _collapse_profile_contract_versions(_filter_profile_rows(rows, **filters))
    period_rows = [
        row
        for row in rows
        if row.get("activity_date") and period_from <= row["activity_date"] < cutoff
    ]
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
    profile_contracts = [
        row for row in period_rows if row.get("activity_type") == "contract"
    ]
    awards = [row for row in period_rows if row.get("activity_type") == "award"]
    contracts = [
        {
            **row,
            "activity_type": "contract",
            "activity_date": row.get("first_contract_date"),
            "event_amount": row.get("contract_amount"),
            "bid_notice_id": None,
            "notice_name": row.get("contract_name"),
        }
        for row in peer_contract_rows
        if str(row.get("organization_code")) == organization_code
        and row.get("first_contract_date")
        and period_from <= row["first_contract_date"] < cutoff
    ]

    companies: dict[str, dict[str, Any]] = {}
    event_keys: set[str] = set()
    excluded: set[str] = set()
    total_amount = Decimal("0")
    for row in contracts:
        number = str(row.get("company_number") or "").strip()
        if not number:
            continue
        item = companies.setdefault(
            number,
            {
                "company_number": number,
                "company_name": row.get("company_name"),
                "contracts": set(),
                "awards": set(),
                "amount": Decimal("0"),
                "dates": [],
                "years": set(),
                "statuses": [],
            },
        )
        key = str(row.get("event_key") or "")
        item["contracts"].add(key)
        event_keys.add(key)
        item["dates"].append(row.get("first_contract_date") or row["activity_date"])
        item["years"].add(row["activity_date"].year)
        item["statuses"].append(str(row.get("amount_completeness") or "unknown"))
        amount = row.get("attributed_contract_amount")
        if amount is None:
            excluded.add(key)
        else:
            amount = Decimal(str(amount))
            item["amount"] += amount
            total_amount += amount
    for row in awards:
        number = str(row.get("company_number") or "")
        if number in companies:
            companies[number]["awards"].add(str(row.get("event_key") or ""))
    ranked = sorted(
        companies.values(), key=lambda item: (-item["amount"], item["company_number"])
    )

    def share(size: int) -> float | None:
        if not total_amount:
            return None
        return round(
            float(
                sum((item["amount"] for item in ranked[:size]), Decimal("0"))
                / total_amount
            ),
            6,
        )

    reference_year = cutoff.year
    target_from = date(reference_year, 1, 1)
    lookback_from = date(reference_year - 3, 1, 1)
    target_companies = {
        str(row["company_number"])
        for row in rows
        if row.get("activity_type") == "contract"
        and row.get("company_number")
        and target_from <= row["activity_date"] < cutoff
    }
    prior_companies = {
        str(row["company_number"])
        for row in rows
        if row.get("activity_type") == "contract"
        and row.get("company_number")
        and lookback_from <= row["activity_date"] < target_from
    }
    new_companies = target_companies - prior_companies
    market_entry = {
        "status": "available" if target_companies else "unavailable",
        "population": "contracted_companies",
        "reference_year": reference_year,
        "is_year_to_date": True,
        "period_from": target_from,
        "period_to": cutoff - timedelta(days=1),
        "lookback_years": 3,
        "contracted_company_count": len(target_companies),
        "new_supplier_company_count": len(new_companies),
        "new_supplier_rate": round(len(new_companies) / len(target_companies), 6)
        if target_companies
        else None,
        "definition": "reference_year_contracted_companies_without_contracts_in_previous_3_fiscal_years",
        "completeness": "complete",
        "reason": None if target_companies else "no_reference_year_contracts",
    }

    current_amount, amount_basis = _representative_notice_amount(notice)
    past_amounts = sorted(
        Decimal(str(value))
        for row in notices
        if (value := _representative_notice_amount(row)[0]) is not None
    )
    project_scale = {
        "status": "available"
        if current_amount is not None and past_amounts
        else "unavailable",
        "current_project_amount": _number(current_amount),
        "current_project_amount_basis": amount_basis,
        "comparison_event_count": len(past_amounts),
        "median_project_amount": _number(statistics.median(past_amounts))
        if past_amounts
        else None,
        "percentile": round(
            sum(value <= Decimal(str(current_amount)) for value in past_amounts)
            / len(past_amounts),
            6,
        )
        if current_amount is not None and past_amounts
        else None,
        "percentile_method": "percent_rank_inclusive",
        "amount_completeness": "complete" if past_amounts else "unknown",
    }

    participant_counts = [
        int(row["participant_count"])
        for row in competition_rows
        if row.get("participant_count") is not None
    ]
    recent, previous = participant_counts[:5], participant_counts[5:10]
    competition = {
        "status": "available" if participant_counts else "unavailable",
        "source_bid_count": len(competition_rows),
        "participant_count_available_bid_count": len(participant_counts),
        "excluded_bid_count": len(competition_rows) - len(participant_counts),
        "overall_average_participant_count": round(
            statistics.mean(participant_counts), 3
        )
        if participant_counts
        else None,
        "overall_median_participant_count": _number(
            statistics.median(participant_counts)
        )
        if participant_counts
        else None,
        "recent_5_average_participant_count": round(statistics.mean(recent), 3)
        if recent
        else None,
        "previous_5_average_participant_count": round(statistics.mean(previous), 3)
        if previous
        else None,
        "three_or_fewer_share": round(
            sum(value <= 3 for value in participant_counts) / len(participant_counts), 6
        )
        if participant_counts
        else None,
        "eight_or_more_share": round(
            sum(value >= 8 for value in participant_counts) / len(participant_counts), 6
        )
        if participant_counts
        else None,
        "completeness": "complete"
        if participant_counts and len(participant_counts) == len(competition_rows)
        else "partial"
        if participant_counts
        else "unknown",
        "completeness_reason": None
        if participant_counts and len(participant_counts) == len(competition_rows)
        else "source_participant_count_missing_for_some_bids",
    }

    peer_benchmark = (
        _build_peer_benchmark(
            peer_contract_rows,
            peer_competition_rows,
            current_organization_code=organization_code,
            period_from=period_from,
            cutoff=cutoff,
            filters=filters,
        )
        if peer_contract_rows or peer_competition_rows
        else {
            "status": "unavailable",
            "reason": "peer_market_data_unavailable",
            "interpretation_allowed": False,
            "benchmark_available": False,
            "minimum_sample_satisfied": False,
        }
    )

    reference_amount = (
        Decimal(str(current_amount)) if current_amount is not None else None
    )
    minimum_amount = reference_amount / Decimal("2") if reference_amount else None
    maximum_amount = reference_amount * Decimal("2") if reference_amount else None
    current_peer_rows = contracts
    peer_history: dict[str, list[date]] = {}
    for row in peer_contract_rows:
        if str(row.get("organization_code")) == organization_code and row.get(
            "company_number"
        ):
            peer_history.setdefault(str(row["company_number"]), []).append(
                row["first_contract_date"]
            )
    case_candidates = []
    seen_cases: set[tuple[str, str]] = set()
    for row in current_peer_rows:
        amount = row.get("attributed_contract_amount")
        company_number = str(row.get("company_number") or "")
        event_date = row["first_contract_date"]
        key = (str(row.get("event_key")), company_number)
        if (
            key in seen_cases
            or not company_number
            or amount is None
            or reference_amount is None
        ):
            continue
        seen_cases.add(key)
        numeric = Decimal(str(amount))
        if not (minimum_amount <= numeric <= maximum_amount):
            continue
        relationship = _contract_time_relationship(
            event_date,
            peer_history.get(company_number, []),
        )
        previous_count = relationship["prior_same_organization_field_contract_count"]
        if relationship["contract_time_relationship_status"] != "entry_or_reentering":
            continue
        matched_contract = next(
            (
                item
                for item in profile_contracts
                if str(item.get("event_key")) == str(row.get("event_key"))
                and str(item.get("company_number")) == company_number
            ),
            None,
        )
        linked_bid_notice_id = (matched_contract or {}).get("bid_notice_id")
        if linked_bid_notice_id and str(linked_bid_notice_id).startswith("contract:"):
            linked_bid_notice_id = None
        case_candidates.append(
            {
                "company_number": company_number,
                "company_name": row.get("company_name"),
                "contract_event_id": row.get("event_key"),
                "unified_contract_number": row.get("unified_contract_number"),
                "contract_name": row.get("contract_name"),
                "latest_contract_version_date": row.get("latest_contract_version_date"),
                "bid_notice_id": linked_bid_notice_id,
                "notice_name": row.get("notice_name")
                or (matched_contract or {}).get("notice_name")
                or row.get("contract_name"),
                "organization_code": organization_code,
                "organization_name": notice.get("organization_name"),
                "work_type": work_type,
                "field_filter": filters,
                "first_contract_date": event_date,
                "attributed_contract_amount": _number(numeric),
                "current_notice_amount_difference_rate": round(
                    float(abs(numeric - reference_amount) / reference_amount), 6
                ),
                "previous_3_fiscal_year_contract_count": 0,
                "new_supplier_basis": "no_same_organization_field_contract_in_previous_3_fiscal_years",
                "entry_classification": "entry_or_reentering",
                **relationship,
                "amount_completeness": row.get("amount_completeness"),
                "notice_lineage_id": (matched_contract or {}).get("notice_lineage_id")
                if linked_bid_notice_id
                else None,
                "notice_linkage": "linked" if linked_bid_notice_id else "unlinked",
                "relationship_context": {
                    "organization_code": organization_code,
                    "company_number": company_number,
                    "contract_event_id": row.get("event_key"),
                    "period_from_year": period_from.year,
                    "period_to_year": (cutoff - timedelta(days=1)).year,
                    **filters,
                },
            }
        )
    case_candidates.sort(
        key=lambda item: (
            item["current_notice_amount_difference_rate"],
            -item["first_contract_date"].toordinal(),
            -float(item["attributed_contract_amount"]),
        )
    )
    eligible_case_event_ids = {
        str(item["contract_event_id"]) for item in case_candidates
    }
    similar_amount_event_ids = {
        str(row["event_key"])
        for row in current_peer_rows
        if reference_amount is not None
        and row.get("contract_amount") is not None
        and minimum_amount <= Decimal(str(row["contract_amount"])) <= maximum_amount
    }
    new_supplier_cases = {
        "status": "available" if reference_amount is not None else "unavailable",
        "reference_amount": _number(reference_amount),
        "amount_range": {
            "minimum_amount": _number(minimum_amount),
            "maximum_amount": _number(maximum_amount),
            "rule": "0.5x_to_2.0x",
            "comparison_rule": "candidate_amount_between_0.5x_and_2.0x_reference",
        },
        "case_unit": "contract_event",
        "eligible_case_count": len(eligible_case_event_ids),
        "similar_amount_contract_event_count": len(similar_amount_event_ids),
        "excluded_missing_amount_count": sum(
            row.get("attributed_contract_amount") is None for row in current_peer_rows
        ),
        "completeness": "partial"
        if any(
            row.get("attributed_contract_amount") is None for row in current_peer_rows
        )
        else "complete",
        "items": case_candidates[:5],
    }

    attention_suppliers, attention_selection_basis = _build_attention_suppliers(
        current_peer_rows,
        history=peer_history,
        cutoff=cutoff,
        period_from=period_from,
        filters=filters,
        organization_code=organization_code,
        reference_amount=reference_amount,
    )

    other_field_by_company: dict[str, dict[str, Any]] = {}
    for row in peer_contract_rows:
        number = str(row.get("company_number") or "")
        if not number or not (period_from <= row["first_contract_date"] < cutoff):
            continue
        bucket = other_field_by_company.setdefault(
            number, {"events": set(), "amount": Decimal("0")}
        )
        if str(row.get("organization_code")) != organization_code:
            bucket["events"].add(
                (str(row.get("organization_code")), str(row.get("event_key")))
            )
            if row.get("attributed_contract_amount") is not None:
                bucket["amount"] += Decimal(str(row["attributed_contract_amount"]))

    top_suppliers = []
    for rank, item in enumerate(ranked[:5], 1):
        years = sorted(item["years"])
        consecutive = 0
        expected = years[-1] if years else None
        for year in reversed(years):
            if year != expected:
                break
            consecutive += 1
            expected -= 1
        external = other_field_by_company.get(
            item["company_number"], {"events": set(), "amount": Decimal("0")}
        )
        similar_count = sum(
            similar
            for event, _, similar in [
                (
                    row,
                    False,
                    reference_amount is not None
                    and row.get("attributed_contract_amount") is not None
                    and minimum_amount
                    <= Decimal(str(row["attributed_contract_amount"]))
                    <= maximum_amount,
                )
                for row in contracts
                if str(row.get("company_number")) == item["company_number"]
            ]
        )
        reasons = ["top_contract_amount"]
        if len(item["contracts"]) >= 2:
            reasons.append("repeated_contracts")
        if item["dates"] and max(item["dates"]) >= cutoff - timedelta(days=365):
            reasons.append("recent_contract")
        if item["amount"] >= Decimal("1000000000"):
            reasons.append("large_contract_history")
        if similar_count:
            reasons.append("similar_amount_experience")
        if any(
            case["company_number"] == item["company_number"] for case in case_candidates
        ):
            reasons.append("new_supplier_contract_case")
        if len(item["contracts"]) >= len(external["events"]):
            reasons.append("organization_specialist")
        if external["events"]:
            reasons.append("field_specialist")
        reason_values = {
            "top_contract_amount": ("attributed_contract_amount_rank", rank, 5),
            "repeated_contracts": (
                "same_organization_field_contract_count",
                len(item["contracts"]),
                2,
            ),
            "recent_contract": (
                "days_since_latest_contract",
                (cutoff - max(item["dates"])).days if item["dates"] else None,
                365,
            ),
            "large_contract_history": (
                "same_organization_field_contract_amount",
                _number(item["amount"]),
                1000000000,
            ),
            "similar_amount_experience": (
                "similar_amount_contract_count",
                similar_count,
                1,
            ),
            "new_supplier_contract_case": (
                "new_supplier_case_count",
                sum(
                    case["company_number"] == item["company_number"]
                    for case in case_candidates
                ),
                1,
            ),
            "organization_specialist": (
                "same_organization_field_contract_count",
                len(item["contracts"]),
                len(external["events"]),
            ),
            "field_specialist": (
                "other_organization_same_field_contract_count",
                len(external["events"]),
                1,
            ),
        }
        attention_evidence = [
            {
                "reason": (
                    "entry_or_reentering_contract_case"
                    if reason == "new_supplier_contract_case"
                    else reason
                ),
                "metric": reason_values[reason][0],
                "value": reason_values[reason][1],
                "threshold": reason_values[reason][2],
            }
            for reason in reasons
        ]
        reasons = [
            (
                "entry_or_reentering_contract_case"
                if reason == "new_supplier_contract_case"
                else reason
            )
            for reason in reasons
        ]
        top_suppliers.append(
            {
                "company_number": item["company_number"],
                "company_name": item["company_name"],
                "award_event_count": len(item["awards"]),
                "contract_event_count": len(item["contracts"]),
                "attributed_contract_amount": _number(item["amount"]),
                "same_organization_field_contract_count": len(item["contracts"]),
                "same_organization_field_contract_amount": _number(item["amount"]),
                "same_organization_other_field_contract_count": None,
                "other_organization_same_field_contract_count": len(external["events"]),
                "other_organization_same_field_contract_amount": _number(
                    external["amount"]
                ),
                "similar_amount_contract_count": similar_count,
                "latest_contract_date": max(item["dates"]) if item["dates"] else None,
                "latest_same_field_contract_date": max(item["dates"])
                if item["dates"]
                else None,
                "active_years": years,
                "consecutive_active_years": consecutive,
                "entry_classification": "incumbent"
                if item["company_number"] in prior_companies
                else "new_supplier",
                "new_supplier_case_count": sum(
                    case["company_number"] == item["company_number"]
                    for case in case_candidates
                ),
                "attention_reasons": reasons,
                "attention_reason_evidence": attention_evidence,
                "amount_completeness": _amount_completeness(item["statuses"]),
            }
        )

    award_by_notice = {
        notice_member_to_lineage.get(
            str(row.get("bid_notice_id")), str(row.get("bid_notice_id"))
        ): row
        for row in awards
    }
    contract_by_notice = {
        notice_member_to_lineage.get(
            str(row.get("bid_notice_id")), str(row.get("bid_notice_id"))
        ): row
        for row in profile_contracts
    }
    related = []
    for row in sorted(
        notices,
        key=lambda item: item.get("notice_published_date") or date.min,
        reverse=True,
    )[:5]:
        notice_id = str(row.get("bid_notice_id"))
        lineage_id = str(row.get("notice_lineage_id") or notice_id)
        award = award_by_notice.get(lineage_id)
        contract = contract_by_notice.get(lineage_id)
        related.append(
            {
                "bid_notice_id": notice_id,
                "notice_name": row.get("notice_name"),
                "notice_kind": row.get("notice_kind"),
                "notice_lineage_id": lineage_id,
                "lineage_count": row.get("lineage_count", 1),
                "root_bid_notice_id": row.get("root_bid_notice_id") or notice_id,
                "relationship_type": "same_field",
                "matched_factors": [
                    "same_organization",
                    "same_work_type",
                    "same_procurement_field",
                ],
                "notice_published_at": row.get("notice_published_date"),
                "awarded_company_number": award.get("company_number")
                if award
                else None,
                "awarded_company_name": award.get("company_name") if award else None,
                "contract_amount": _number(contract.get("event_amount"))
                if contract
                else None,
                "contract_date": contract.get("first_contract_date")
                if contract
                else None,
            }
        )

    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        kind="execution",
        source="teoria_runtime",
        operation="market_context.analyze_bid_participation_context",
        mapping="public_procurement_market_context",
        observed_at=observed_at,
        record_keys=[bid_notice_id],
    )
    properties = {
        "bid_participation_context_id": bid_notice_id,
        "bid_notice_id": bid_notice_id,
    }
    entry_amount = Decimal("0")
    incumbent_amount = Decimal("0")
    for row in current_peer_rows:
        amount = row.get("attributed_contract_amount")
        if amount is None or not row.get("company_number"):
            continue
        event_date = row["first_contract_date"]
        prior_from = date(event_date.year - 3, 1, 1)
        is_entry = not any(
            prior_from <= value < date(event_date.year, 1, 1)
            for value in peer_history.get(str(row["company_number"]), [])
        )
        if is_entry:
            entry_amount += Decimal(str(amount))
        else:
            incumbent_amount += Decimal(str(amount))
    reconciliation = {
        "contract_event_count": len(event_keys),
        "contracted_company_count": len(companies),
        "total_contract_amount": _number(total_amount),
        "top_supplier_amount_sum": _number(
            sum((item["amount"] for item in ranked[:5]), Decimal("0"))
        ),
        "new_or_reentering_contract_amount": _number(entry_amount),
        "incumbent_contract_amount": _number(incumbent_amount),
        "excluded_contract_count": len(excluded),
        "amount_difference": _number(total_amount - entry_amount - incumbent_amount),
    }
    result = CapabilityResult(
        capability_id=capability_id,
        objects=[
            MaterializedObject(
                ontology="public_procurement",
                object_type="bid_participation_context",
                object_id=bid_notice_id,
                properties=properties,
                provenance=[provenance],
                property_provenance={key: [provenance] for key in properties},
            )
        ],
        outcome={
            "analysis_basis": {
                "bid_notice_id": bid_notice_id,
                "notice_published_at": cutoff,
                "period_from": period_from,
                "period_to": cutoff - timedelta(days=1),
                "period_years": period_years,
                "organization_code": organization_code,
                "work_type": work_type,
                "field_filter": filters,
                "contract_population_basis": {
                    "organization_code": organization_code,
                    "work_type": work_type,
                    "field_filter": filters,
                    "period_from": period_from,
                    "period_to": cutoff - timedelta(days=1),
                    "event_unit": "original_contract_event",
                    "version_policy": "latest_version_available_in_ledger",
                    "lineage_policy": "one_procurement_project_per_notice_lineage",
                    "consortium_attribution_policy": "source_share_else_single_supplier_full_else_unattributed",
                    "missing_amount_policy": "excluded",
                },
            },
            "market_entry": market_entry,
            "supplier_concentration": {
                "status": "available" if companies else "unavailable",
                "company_count": len(companies),
                "contract_event_count": len(event_keys),
                "total_contract_amount": _number(total_amount),
                "top_1_share": share(1),
                "top_3_share": share(3),
                "top_5_share": share(5),
                "amount_completeness": "complete" if not excluded else "partial",
                "excluded_contract_count": len(excluded),
            },
            "project_scale": project_scale,
            "competition": competition,
            "peer_benchmark": peer_benchmark,
            "new_supplier_similar_amount_cases": new_supplier_cases,
            "reconciliation": reconciliation,
            "attention_suppliers": attention_suppliers,
            "attention_suppliers_selection_basis": attention_selection_basis,
            "selection_basis": {"attention_suppliers": attention_selection_basis},
            "top_suppliers": top_suppliers,
            "related_past_projects": related,
            "top_suppliers_basis": {
                "limit": 5,
                "ranking": "attributed_contract_amount_desc",
                "population": "contracted_companies",
                "sample_company_count": len(companies),
                "attention_reason_policy": {
                    "top_contract_amount": "top_5_attributed_contract_amount_within_population",
                    "repeated_contracts": "same_organization_field_contract_count_gte_2",
                    "recent_contract": "latest_contract_within_365_days_before_notice",
                    "large_contract_history": "same_organization_field_amount_gte_1_billion_krw",
                    "similar_amount_experience": "attributed_amount_between_0.5x_and_2.0x_reference",
                    "new_supplier_contract_case": "entry_or_reentry_similar_amount_case_exists",
                    "organization_specialist": "organization_field_events_gte_other_organization_field_events",
                    "field_specialist": "other_organization_same_field_event_exists",
                },
            },
            "related_past_projects_basis": {
                "limit": 5,
                "relationship_types_returned": ["same_field"],
                "previous_project_requires_lineage_evidence": True,
                "sample_notice_count": len(notices),
            },
            "data_completeness": {
                "status": "partial"
                if (
                    excluded
                    or project_scale["status"] == "unavailable"
                    or competition["completeness"] != "complete"
                )
                else "complete",
                "missing_reasons": [
                    reason
                    for condition, reason in (
                        (bool(excluded), "some_contract_amounts_not_attributable"),
                        (
                            project_scale["status"] == "unavailable",
                            "comparable_notice_amount_unavailable",
                        ),
                        (
                            competition["completeness"] != "complete",
                            "source_participant_count_missing_for_some_bids",
                        ),
                        (
                            peer_benchmark.get("status") != "available",
                            "peer_benchmark_unavailable",
                        ),
                    )
                    if condition
                ],
            },
            "registry_version": registry_version,
            "timings": {
                "total_ms": round((time.perf_counter() - started) * 1000, 3),
                "cache_hit": False,
            },
        },
    )
    if reader is None and cache is not None:
        await cache.set(cache_key, result, 600)
    elif reader is None:
        _BID_PARTICIPATION_CONTEXT_CACHE[cache_key] = (
            time.monotonic(),
            result.model_copy(deep=True),
        )
    return result


_BID_PARTICIPATION_CONTEXT_CACHE: dict[
    tuple[str, int, str], tuple[float, CapabilityResult]
] = {}
