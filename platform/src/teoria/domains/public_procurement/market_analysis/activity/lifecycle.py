from __future__ import annotations

from datetime import date, datetime, timezone


def resolve_activity_stages(activities: dict, stage_as_of: datetime) -> list[dict]:
    filtered_before_stage = []
    for activity in activities.values():
        activity["awards"].sort(
            key=lambda value: value.get("award_date") or date.min,
            reverse=True,
        )
        activity["contracts"].sort(
            key=lambda value: value.get("contract_date") or date.min,
            reverse=True,
        )
        activity["award"] = activity["awards"][0] if activity["awards"] else None
        activity["contract"] = (
            activity["contracts"][0] if activity["contracts"] else None
        )
        if activity["notice_linkage"] == "linked" and activity["notice"] is not None:
            notice_amounts = activity["notice"]
            amount_candidates = (
                ("allocated_budget", "배정예산"),
                ("estimated_price", "추정가격"),
                ("base_amount", "기초금액"),
            )
            selected_amount = next(
                (
                    (notice_amounts[basis], basis, basis_name)
                    for basis, basis_name in amount_candidates
                    if notice_amounts.get(basis) is not None
                ),
                (None, None, None),
            )
        elif activity["contract"] is not None:
            selected_amount = (
                activity["contract"].get("contract_amount"),
                "contract_amount",
                "계약금액",
            )
        elif activity["award"] is not None:
            selected_amount = (
                activity["award"].get("winning_amount"),
                "winning_amount",
                "낙찰금액",
            )
        else:
            selected_amount = (None, None, None)
        (
            activity["project_amount"],
            activity["project_amount_basis"],
            activity["project_amount_basis_name"],
        ) = selected_amount
        if activity["contract"]:
            stage = "contract"
            latest_activity_date = activity["contract"]["contract_date"]
        elif activity["award"]:
            stage = "award"
            latest_activity_date = activity["award"]["award_date"]
        elif activity.get("_current_status") in {"cancelled", "failed"}:
            stage = str(activity["_current_status"])
            latest_activity_date = (
                activity["notice"].get("cancellation_at")
                if stage == "cancelled"
                else activity["notice"].get("failure_at")
            ) or activity["notice"]["published_at"]
        else:
            activity.pop("_bid_status", None)
            published_at = activity["notice"]["published_at"]
            deadline_at = activity["notice"]["deadline_at"]
            published_moment = (
                published_at
                if isinstance(published_at, datetime)
                else datetime.combine(published_at, datetime.min.time(), timezone.utc)
            )
            if published_moment.tzinfo is None:
                published_moment = published_moment.replace(tzinfo=timezone.utc)
            deadline_moment = None
            if deadline_at is not None:
                deadline_moment = (
                    deadline_at
                    if isinstance(deadline_at, datetime)
                    else datetime.combine(
                        deadline_at, datetime.min.time(), timezone.utc
                    )
                )
                if deadline_moment.tzinfo is None:
                    deadline_moment = deadline_moment.replace(tzinfo=timezone.utc)
            stage = (
                "scheduled"
                if published_moment > stage_as_of
                else "open"
                if deadline_moment is not None and stage_as_of < deadline_moment
                else "closed"
            )
            latest_activity_date = published_at
        activity.pop("_notice_status", None)
        activity.pop("_current_status", None)
        activity.pop("_bid_status", None)
        activity["stage"] = stage
        activity["stage_name"] = {
            "scheduled": "예정",
            "open": "진행",
            "closed": "마감",
            "award": "낙찰",
            "contract": "계약",
            "failed": "유찰",
            "cancelled": "취소",
        }[stage]
        activity["latest_activity_date"] = (
            latest_activity_date.date()
            if isinstance(latest_activity_date, datetime)
            else latest_activity_date
        )
        filtered_before_stage.append(activity)

    return filtered_before_stage


def expand_activity_records(
    filtered_before_stage: list[dict], contract_classifications: dict
) -> list[dict]:
    expanded_records = []
    for activity in filtered_before_stage:
        if activity["contracts"]:
            for contract in activity["contracts"]:
                record = {
                    **activity,
                    **contract_classifications.get(contract["contract_event_id"], {}),
                    "activity_id": f"contract:{contract['contract_event_id']}",
                    "stage": "contract",
                    "stage_name": "계약",
                    "contracts": [contract],
                    "contract": contract,
                    "latest_activity_date": contract["first_contract_date"],
                    "project_amount": contract.get("contract_amount"),
                    "project_amount_basis": "contract_amount",
                    "project_amount_basis_name": "계약금액",
                }
                expanded_records.append(record)
        elif activity["awards"]:
            for award in activity["awards"]:
                record = {
                    **activity,
                    "activity_id": f"award:{award['award_id']}",
                    "stage": "award",
                    "stage_name": "낙찰",
                    "awards": [award],
                    "award": award,
                    "latest_activity_date": award["award_date"],
                    "project_amount": award.get("winning_amount"),
                    "project_amount_basis": "winning_amount",
                    "project_amount_basis_name": "낙찰금액",
                }
                expanded_records.append(record)
        else:
            expanded_records.append(activity)

    return expanded_records
