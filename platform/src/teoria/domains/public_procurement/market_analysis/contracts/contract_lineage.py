from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..related_projects.similarity import number as _number


def _contract_structure(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized == "장기":
        return "long_term_continuing"
    if normalized == "계속비":
        return "installment"
    if normalized == "신규":
        return "single"
    return "unknown"


def _contract_phase_number(contract_name: Any) -> int | None:
    match = _CONTRACT_PHASE_PATTERN.search(str(contract_name or ""))
    return int(match.group(1)) if match else None


def _contract_family_name(contract_name: Any) -> str | None:
    value = _CONTRACT_FAMILY_MARKER_PATTERN.sub(" ", str(contract_name or ""))
    value = " ".join(value.casefold().split())
    return value or None


def _contract_event_identity(source: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "confirmed_contract_number",
        "contract_reference_number",
        "unified_contract_number",
    ):
        value = str(source.get(field) or "").strip()
        if value:
            return {"field": field, "value": value}
    return {"field": None, "value": None}


def _contract_source_numbers(source: dict[str, Any]) -> dict[str, Any]:
    return {
        field: source.get(field)
        for field in (
            "confirmed_contract_number",
            "contract_reference_number",
            "unified_contract_number",
        )
    }


def _official_contract_change_identity(
    source: dict[str, Any],
) -> dict[str, Any] | None:
    detail_url = str(source.get("contract_detail_url") or "").strip()
    if not detail_url:
        return None
    parameters = parse_qs(urlparse(detail_url).query)
    contract_number = str((parameters.get("ctrtNo") or [""])[0]).strip()
    change_order = str((parameters.get("ctrtChgOrd") or [""])[0]).strip()
    if not contract_number or not change_order.isdigit():
        return None
    combined = f"{contract_number}{change_order}"
    source_numbers = {
        str(source.get("confirmed_contract_number") or "").strip(),
        str(source.get("contract_reference_number") or "").strip(),
    }
    if combined not in source_numbers:
        return None
    return {
        "contract_number": contract_number,
        "change_order": int(change_order),
        "change_order_raw": change_order,
        "evidence_field": "contract_detail_url_query",
    }


def _decorate_contract_amount(
    contract: dict[str, Any],
    source: dict[str, Any],
) -> None:
    source_total = _number(source.get("total_amount"))
    current_amount = contract.get("current_contract_amount")
    structure = contract.get("contract_structure")
    if source_total not in {None, 0}:
        total_amount = source_total
        total_basis = "source_total_amount"
    elif structure == "single" and current_amount not in {None, 0}:
        total_amount = current_amount
        total_basis = "current_contract_amount_for_single_contract"
    else:
        total_amount = None
        total_basis = (
            "source_total_zero_treated_as_unavailable"
            if source_total == 0
            else "source_total_missing"
        )
    contract.update(
        {
            "total_contract_amount": total_amount,
            "total_contract_amount_basis": total_basis,
            "phase_contract_amount": current_amount,
            "amount_tax_basis": "unknown",
        }
    )


def _decorate_contract_lineage(
    contracts: list[dict[str, Any]],
    *,
    bid_notice_id: str | None,
) -> None:
    """Add evidence-labelled family metadata without asserting title-based identity."""
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = {}
    official_families: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        source = contract.get("_lineage_source") or {}
        structure = _contract_structure(source.get("long_term_continuation_type"))
        contract["contract_structure"] = structure
        contract["phase_number"] = _contract_phase_number(source.get("contract_name"))
        _decorate_contract_amount(contract, source)
        family_name = _contract_family_name(source.get("contract_name"))
        contract["_series_candidate"] = {
            "bid_notice_id": bid_notice_id,
            "contract_structure": structure,
            "normalized_contract_name": family_name,
            "long_term_continuation_type": source.get("long_term_continuation_type"),
            "request_number": source.get("request_number"),
        }
        official_identity = _official_contract_change_identity(source)
        contract["_official_contract_identity"] = official_identity
        if official_identity is not None:
            official_families.setdefault(
                str(official_identity["contract_number"]), []
            ).append(contract)
        if structure in {"long_term_continuing", "installment"} and family_name:
            candidates.setdefault((structure, family_name), []).append(contract)

    decorated_members: set[int] = set()
    for contract_number, members in official_families.items():
        members.sort(
            key=lambda value: (
                int((value.get("_official_contract_identity") or {})["change_order"]),
                value.get("first_contract_date") or date.max,
                str(value.get("contract_event_id") or ""),
            )
        )
        original = next(
            (
                member
                for member in members
                if (member.get("_official_contract_identity") or {}).get("change_order")
                == 0
            ),
            None,
        )
        original_id = original.get("contract_event_id") if original else None
        for index, member in enumerate(members):
            source = member.get("_lineage_source") or {}
            identity = member.get("_official_contract_identity")
            decorated_members.add(id(member))
            is_original = int(identity["change_order"]) == 0
            is_current = index == len(members) - 1
            effective_amount = member.get("total_contract_amount")
            previous = members[index - 1] if index > 0 else None
            previous_identity = (
                previous.get("_official_contract_identity") if previous else None
            )
            next_member = members[index + 1] if index + 1 < len(members) else None
            next_identity = (
                next_member.get("_official_contract_identity") if next_member else None
            )
            member.update(
                {
                    "contract_family_id": f"contract-family:source:{contract_number}",
                    "contract_record_type": "original" if is_original else "amendment",
                    "parent_contract_event_id": (
                        previous.get("contract_event_id")
                        if previous is not None
                        and int(previous_identity["change_order"]) + 1
                        == int(identity["change_order"])
                        else None
                    ),
                    "original_contract_event_id": original_id,
                    "is_current_record": is_current,
                    "superseded_by_contract_event_id": (
                        next_member.get("contract_event_id")
                        if next_member is not None
                        and int(identity["change_order"]) + 1
                        == int(next_identity["change_order"])
                        else None
                    ),
                    "amount_record_type": (
                        "initial_total" if is_original else "current_total"
                    ),
                    "effective_contract_amount": effective_amount,
                    "include_in_family_total": is_current
                    and effective_amount is not None,
                    "relationship_status": "confirmed",
                    "relationship_basis": {
                        "contract_event_identity": _contract_event_identity(source),
                        "source_contract_numbers": _contract_source_numbers(source),
                        "source_contract_family": {
                            **identity,
                            "confirmed_number_matches_contract_number_and_change_order": True,
                        },
                        "amount_basis": member.get("total_contract_amount_basis"),
                        "family_inference": None,
                    },
                }
            )

    for (structure, family_name), members in candidates.items():
        members = [member for member in members if id(member) not in decorated_members]
        if len(members) < 2:
            continue
        family_evidence = "|".join((str(bid_notice_id or ""), structure, family_name))
        family_id = (
            "contract-family:inferred:"
            + hashlib.sha256(family_evidence.encode("utf-8")).hexdigest()[:20]
        )
        original = min(
            members,
            key=lambda value: (
                0
                if "총괄"
                in str((value.get("_lineage_source") or {}).get("contract_name") or "")
                else 1,
                value.get("phase_number")
                if value.get("phase_number") is not None
                else 10**9,
                value.get("first_contract_date") or date.max,
                str(value.get("contract_event_id") or ""),
            ),
        )
        original_id = original.get("contract_event_id")
        phase_sequences: dict[int, list[dict[str, Any]]] = {}
        for member in members:
            phase_number = member.get("phase_number")
            if phase_number is not None:
                phase_sequences.setdefault(int(phase_number), []).append(member)
        for phase_members in phase_sequences.values():
            phase_members.sort(
                key=lambda value: (
                    value.get("first_contract_date") or date.max,
                    str(value.get("contract_event_id") or ""),
                )
            )
        chronological_members = sorted(
            members,
            key=lambda value: (
                value.get("first_contract_date") or date.max,
                str(value.get("contract_event_id") or ""),
            ),
        )
        latest_member = chronological_members[-1]
        for member in members:
            source = member.get("_lineage_source") or {}
            member.pop("_official_contract_identity", None)
            decorated_members.add(id(member))
            phase_members = phase_sequences.get(member.get("phase_number"), [])
            phase_index = (
                phase_members.index(member) if member in phase_members else None
            )
            if member is original:
                record_type = "original"
                parent_id = None
                parent_link_basis = None
            elif phase_index is not None and phase_index > 0:
                record_type = "amendment"
                parent_id = phase_members[phase_index - 1].get("contract_event_id")
                parent_link_basis = "same_inferred_family_and_phase_chronology"
            elif member.get("phase_number") is not None:
                record_type = "phase"
                parent_id = original_id
                parent_link_basis = "same_inferred_family_with_phase_marker"
            else:
                record_type = "unknown"
                parent_id = original_id
                parent_link_basis = "same_inferred_family_chronology"
            same_phase_next = None
            if phase_index is not None and phase_index + 1 < len(phase_members):
                same_phase_next = phase_members[phase_index + 1].get(
                    "contract_event_id"
                )
            is_current = member is latest_member
            effective_amount = (
                member.get("total_contract_amount") if is_current else None
            )
            member.update(
                {
                    "contract_family_id": family_id,
                    "contract_record_type": record_type,
                    "parent_contract_event_id": parent_id,
                    "original_contract_event_id": original_id,
                    "is_current_record": is_current,
                    "superseded_by_contract_event_id": same_phase_next,
                    "amount_record_type": (
                        "current_total"
                        if effective_amount is not None
                        else "phase_amount"
                        if member.get("phase_number") is not None
                        else "unknown"
                    ),
                    "effective_contract_amount": (
                        effective_amount
                        if effective_amount is not None
                        else member.get("phase_contract_amount")
                    ),
                    "include_in_family_total": effective_amount is not None,
                    "relationship_status": "inferred",
                    "relationship_basis": {
                        "contract_event_identity": _contract_event_identity(source),
                        "source_contract_numbers": _contract_source_numbers(source),
                        "family_inference": {
                            "bid_notice_id": bid_notice_id,
                            "long_term_continuation_type": source.get(
                                "long_term_continuation_type"
                            ),
                            "normalized_contract_name": family_name,
                            "phase_marker": member.get("phase_number"),
                            "parent_link_basis": parent_link_basis,
                        },
                        "amount_basis": member.get("total_contract_amount_basis"),
                    },
                }
            )

    for contract in contracts:
        source = contract.pop("_lineage_source", {}) or {}
        contract.pop("_official_contract_identity", None)
        if id(contract) in decorated_members:
            continue
        event_id = contract.get("contract_event_id")
        structure = contract.get("contract_structure")
        independent = structure == "single" and event_id is not None
        effective_amount = (
            contract.get("total_contract_amount") if independent else None
        )
        contract.update(
            {
                "contract_family_id": f"contract-family:{event_id}"
                if event_id
                else None,
                "contract_record_type": "independent" if independent else "unknown",
                "parent_contract_event_id": None,
                "original_contract_event_id": event_id if independent else None,
                "is_current_record": True,
                "superseded_by_contract_event_id": None,
                "amount_record_type": "current_total" if independent else "unknown",
                "effective_contract_amount": effective_amount,
                "include_in_family_total": independent and effective_amount is not None,
                "relationship_status": "confirmed" if independent else "unknown",
                "relationship_basis": {
                    "contract_event_identity": _contract_event_identity(source),
                    "source_contract_numbers": _contract_source_numbers(source),
                    "long_term_continuation_type": source.get(
                        "long_term_continuation_type"
                    ),
                    "amount_basis": contract.get("total_contract_amount_basis"),
                    "family_inference": None,
                },
            }
        )

    _decorate_contract_series(contracts, bid_notice_id=bid_notice_id)


def _decorate_contract_series(
    contracts: list[dict[str, Any]],
    *,
    bid_notice_id: str | None,
) -> None:
    """Describe cross-family continuation candidates without asserting identity."""
    families: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        family_id = str(
            contract.get("contract_family_id")
            or f"unresolved:{contract.get('contract_event_id')}"
        )
        families.setdefault(family_id, []).append(contract)

    family_profiles: dict[str, dict[str, Any]] = {}
    candidates: dict[tuple[str, str], list[str]] = {}
    for family_id, members in families.items():
        ordered = sorted(
            members,
            key=lambda value: (
                value.get("first_contract_date") or date.max,
                str(value.get("contract_event_id") or ""),
            ),
        )
        current = next(
            (member for member in members if member.get("is_current_record")),
            ordered[-1],
        )
        candidate = current.get("_series_candidate") or {}
        entry = ordered[0]
        profile = {
            "family_id": family_id,
            "members": members,
            "current": current,
            "candidate": candidate,
            "entry_total": entry.get("total_contract_amount"),
            "current_effective_amount": current.get("effective_contract_amount"),
            "first_contract_date": ordered[0].get("first_contract_date"),
        }
        family_profiles[family_id] = profile
        structure = str(candidate.get("contract_structure") or "")
        family_name = str(candidate.get("normalized_contract_name") or "")
        if structure in {"long_term_continuing", "installment"} and family_name:
            candidates.setdefault((structure, family_name), []).append(family_id)

    decorated_families: set[str] = set()
    for (structure, family_name), family_ids in candidates.items():
        if len(family_ids) < 2:
            continue
        ordered_profiles = sorted(
            (family_profiles[family_id] for family_id in family_ids),
            key=lambda value: (
                value.get("first_contract_date") or date.max,
                value["family_id"],
            ),
        )
        evidence = "|".join((str(bid_notice_id or ""), structure, family_name))
        series_id = (
            "contract-series:inferred:"
            + hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:20]
        )
        original_family_id = ordered_profiles[0]["family_id"]
        for index, profile in enumerate(ordered_profiles):
            family_id = profile["family_id"]
            decorated_families.add(family_id)
            previous = ordered_profiles[index - 1] if index > 0 else None
            previous_amount = (
                previous.get("current_effective_amount") if previous else None
            )
            entry_total = profile.get("entry_total")
            relationship_basis = {
                "bid_notice_id": bid_notice_id,
                "long_term_continuation_type": profile["candidate"].get(
                    "long_term_continuation_type"
                ),
                "normalized_contract_name": family_name,
                "source_request_number": profile["candidate"].get("request_number"),
                "authoritative_series_identifier": None,
                "previous_family_effective_amount": previous_amount,
                "current_family_entry_total": entry_total,
                "previous_total_matches_current_entry_total": (
                    previous_amount is not None
                    and entry_total is not None
                    and previous_amount == entry_total
                ),
            }
            for member in profile["members"]:
                member.update(
                    {
                        "contract_series_id": series_id,
                        "previous_contract_family_id": (
                            previous["family_id"] if previous else None
                        ),
                        "original_contract_family_id": original_family_id,
                        "family_relationship_type": (
                            "continuation" if previous else "unknown"
                        ),
                        "family_relationship_status": "inferred",
                        "family_relationship_basis": relationship_basis,
                    }
                )

    for family_id, profile in family_profiles.items():
        if family_id in decorated_families:
            for member in profile["members"]:
                member.pop("_series_candidate", None)
            continue
        for member in profile["members"]:
            member.pop("_series_candidate", None)
            if member.get("contract_structure") == "single":
                member.update(
                    {
                        "contract_series_id": None,
                        "previous_contract_family_id": None,
                        "original_contract_family_id": family_id,
                        "family_relationship_type": "independent",
                        "family_relationship_status": "confirmed",
                        "family_relationship_basis": {
                            "contract_structure": "single",
                            "authoritative_series_identifier": None,
                        },
                    }
                )
            else:
                member.update(
                    {
                        "contract_series_id": None,
                        "previous_contract_family_id": None,
                        "original_contract_family_id": family_id,
                        "family_relationship_type": "unknown",
                        "family_relationship_status": "unresolved",
                        "family_relationship_basis": {
                            "bid_notice_id": bid_notice_id,
                            "authoritative_series_identifier": None,
                            "reason": "no_cross_family_source_identifier",
                        },
                    }
                )


def _contract_family_summary(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    families: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts:
        family_id = str(
            contract.get("contract_family_id")
            or f"unresolved:{contract.get('contract_event_id')}"
        )
        families.setdefault(family_id, []).append(contract)
    included = [
        contract
        for contract in contracts
        if contract.get("include_in_family_total")
        and contract.get("effective_contract_amount") is not None
    ]
    unresolved_family = any(
        not any(member.get("include_in_family_total") for member in members)
        or sum(bool(member.get("include_in_family_total")) for member in members) != 1
        or any(member.get("relationship_status") == "unknown" for member in members)
        or any(
            member.get("contract_record_type") == "amendment"
            and member.get("original_contract_event_id") is None
            for member in members
        )
        for members in families.values()
    )
    series_families: dict[str, set[str]] = {}
    for family_id, members in families.items():
        series_id = next(
            (
                str(member.get("contract_series_id"))
                for member in members
                if member.get("contract_series_id")
            ),
            None,
        )
        if series_id:
            series_families.setdefault(series_id, set()).add(family_id)
    unresolved_series = any(
        len(family_ids) > 1
        and any(
            member.get("contract_series_id") == series_id
            and member.get("family_relationship_status") != "confirmed"
            for member in contracts
        )
        for series_id, family_ids in series_families.items()
    )
    unresolved = unresolved_family or unresolved_series
    inferred = any(
        contract.get("relationship_status") == "inferred" for contract in contracts
    )
    status = (
        "unresolved"
        if unresolved
        else "partially_confirmed"
        if inferred
        else "confirmed"
    )
    included_family_ids = {
        str(contract.get("contract_family_id")) for contract in included
    }
    included_event_ids = list(
        dict.fromkeys(
            str(contract.get("contract_event_id"))
            for contract in included
            if contract.get("contract_event_id")
        )
    )
    confirmed_amounts = [
        contract
        for contract in included
        if contract.get("relationship_status") == "confirmed"
    ]
    latest_confirmed = max(
        confirmed_amounts,
        key=lambda value: (
            value.get("latest_contract_version_date")
            or value.get("first_contract_date")
            or date.min,
            str(value.get("contract_event_id") or ""),
        ),
        default=None,
    )
    effective_amount = (
        None
        if unresolved
        else sum(contract["effective_contract_amount"] for contract in included)
        if included
        else None
    )
    effective_event_id = (
        included[0].get("contract_event_id")
        if not unresolved and len(included) == 1
        else None
    )
    aggregation_reason = (
        "long_term_continuation_relationship_unresolved"
        if unresolved_series
        else "contract_family_relationship_unresolved"
        if unresolved_family
        else "inferred_contract_family_relationship"
        if inferred
        else "confirmed_contract_family_aggregation"
        if included
        else "no_confirmed_contract_amount"
    )
    return {
        "effective_contract_amount": effective_amount,
        "effective_contract_event_id": effective_event_id,
        "included_contract_event_ids": included_event_ids,
        "latest_confirmed_contract_amount": (
            latest_confirmed.get("effective_contract_amount")
            if latest_confirmed
            else None
        ),
        "latest_confirmed_contract_event_id": (
            latest_confirmed.get("contract_event_id") if latest_confirmed else None
        ),
        "contract_family_count": len(families),
        "included_contract_family_count": len(included_family_ids),
        "amount_aggregation_status": status,
        "amount_aggregation_reason": aggregation_reason,
    }


_CONTRACT_PHASE_PATTERN = re.compile(
    r"(?:\(|\b)(?:장기\s*)?(?:제\s*)?(\d+)\s*차(?:\)|\b)"
)


_CONTRACT_FAMILY_MARKER_PATTERN = re.compile(
    r"\(\s*(?:장기\s*)?(?:제\s*)?\d+\s*차\s*\)|\(\s*총괄\s*\)",
)
