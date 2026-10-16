from __future__ import annotations

import json
from datetime import date
from typing import Any

from ..contracts.contract_lineage import (
    _contract_family_summary,
    _decorate_contract_lineage,
)

_PROCUREMENT_ACTIVITY_STAGE_PRIORITY = {
    "scheduled": 0,
    "open": 1,
    "closed": 2,
    "failed": 3,
    "cancelled": 4,
    "award": 5,
    "contract": 6,
}


def _notice_group_id(record: dict[str, Any]) -> str:
    bid_notice_id = str(record.get("bid_notice_id") or "").strip()
    if bid_notice_id:
        return f"notice:{bid_notice_id}"
    contract = record.get("contract") or {}
    contract_key = str(
        contract.get("contract_event_id")
        or contract.get("unified_contract_number")
        or ""
    ).strip()
    if contract_key:
        return f"contract:{contract_key}"
    award = record.get("award") or {}
    award_key = str(award.get("award_id") or "").strip()
    if award_key:
        return f"award:{award_key}"
    return f"activity:{record['activity_id']}"


def _group_procurement_activity_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        group_id = _notice_group_id(record)
        group = groups.setdefault(
            group_id,
            {
                "activity_group_id": group_id,
                "bid_notice_id": record.get("bid_notice_id"),
                "notice_linkage": record.get("notice_linkage"),
                "notice": None,
                "_records": [],
                "_awards": {},
                "_contracts": {},
            },
        )
        group["_records"].append(record)

        source_notice = record.get("notice")
        if group["notice"] is None and (
            source_notice is not None or record.get("bid_notice_id")
        ):
            source_notice = source_notice or {}
            amount_candidates = (
                ("allocated_budget", "배정예산"),
                ("estimated_price", "추정가격"),
                ("base_amount", "기초금액"),
            )
            project_amount, amount_basis, amount_basis_name = next(
                (
                    (source_notice.get(basis), basis, basis_name)
                    for basis, basis_name in amount_candidates
                    if source_notice.get(basis) is not None
                ),
                (None, None, None),
            )
            group["notice"] = {
                "notice_name": record.get("notice_name"),
                "published_at": source_notice.get("published_at"),
                "bid_begin_at": source_notice.get("bid_begin_at"),
                "deadline_at": source_notice.get("deadline_at"),
                "status": source_notice.get("status"),
                "notice_status": source_notice.get("notice_status"),
                "current_status": source_notice.get("current_status"),
                "current_status_label": source_notice.get("current_status_label"),
                "cancellation_reason": source_notice.get("cancellation_reason"),
                "cancellation_at": source_notice.get("cancellation_at"),
                "failure_reason": source_notice.get("failure_reason"),
                "failure_at": source_notice.get("failure_at"),
                "status_source": source_notice.get("status_source"),
                "status_confirmed_at": source_notice.get("status_confirmed_at"),
                "original_notice_id": source_notice.get("original_notice_id"),
                "current_notice_id": source_notice.get("current_notice_id"),
                "revision_number": source_notice.get("revision_number"),
                "is_latest_revision": source_notice.get("is_latest_revision"),
                "work_type": record.get("work_type"),
                "project_amount": project_amount,
                "project_amount_basis": amount_basis,
                "project_amount_basis_name": amount_basis_name,
            }

        for award in record.get("awards") or []:
            award_key = str(award.get("award_id") or "").strip() or json.dumps(
                award,
                sort_keys=True,
                default=str,
            )
            group["_awards"][award_key] = dict(award)

        for contract in record.get("contracts") or []:
            contract_key = str(
                contract.get("contract_event_id")
                or contract.get("unified_contract_number")
                or ""
            ).strip()
            if not contract_key:
                continue
            grouped_contract = dict(contract)
            grouped_contract["latest_contract_version_date"] = grouped_contract.pop(
                "contract_date",
                None,
            )
            grouped_contract["current_contract_amount"] = grouped_contract.pop(
                "contract_amount",
                None,
            )
            group["_contracts"][contract_key] = grouped_contract

    grouped_records = []
    for group in groups.values():
        records_in_group = group.pop("_records")
        representative = max(
            records_in_group,
            key=lambda item: (
                _PROCUREMENT_ACTIVITY_STAGE_PRIORITY.get(str(item.get("stage")), -1),
                item.get("latest_activity_date") or date.min,
                str(item.get("activity_id") or ""),
            ),
        )
        latest_stage = str(representative["stage"])
        same_stage_dates = [
            item.get("latest_activity_date")
            for item in records_in_group
            if item.get("stage") == latest_stage and item.get("latest_activity_date")
        ]
        awards = list(group.pop("_awards").values())
        awards.sort(
            key=lambda value: (
                value.get("award_date") or date.min,
                str(value.get("award_id") or ""),
            ),
            reverse=True,
        )
        contracts = list(group.pop("_contracts").values())
        _decorate_contract_lineage(
            contracts,
            bid_notice_id=group.get("bid_notice_id"),
        )
        contracts.sort(
            key=lambda value: (
                value.get("first_contract_date") or date.min,
                str(value.get("contract_event_id") or ""),
            ),
            reverse=True,
        )
        contract_family_summary = _contract_family_summary(contracts)
        group.update(
            {
                "latest_stage": latest_stage,
                "latest_stage_name": representative.get("stage_name"),
                "latest_activity_date": max(same_stage_dates)
                if same_stage_dates
                else None,
                "notice_name": representative.get("notice_name"),
                "organization_code": representative.get("organization_code"),
                "organization_name": representative.get("organization_name"),
                "work_type": representative.get("work_type"),
                "field_code": representative.get("field_code"),
                "field_name": representative.get("field_name"),
                "large_category": representative.get("large_category"),
                "middle_category": representative.get("middle_category"),
                "awards": awards,
                "contracts": contracts,
                "result_summary": {
                    "award_count": len(awards),
                    "contract_event_count": len(contracts),
                    "contract_version_count": sum(
                        int(contract.get("contract_version_count") or 0)
                        for contract in contracts
                    ),
                    **contract_family_summary,
                },
            }
        )
        grouped_records.append(group)
    return grouped_records
