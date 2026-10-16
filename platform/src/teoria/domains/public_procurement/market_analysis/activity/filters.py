from __future__ import annotations

from ..field_identity import _normalized_category
from .models import ActivityEvents
from .query import ActivityQuery


def filter_activity_records(
    expanded_records: list[dict], request: ActivityQuery, events: ActivityEvents
) -> list[dict]:
    filtered_records = []
    for record in expanded_records:
        if request.work_type and record.get("work_type") != request.work_type:
            continue
        if (
            request.large_category
            and _normalized_category(record.get("large_category"))
            != request.large_category
        ):
            continue
        if (
            request.middle_category
            and _normalized_category(record.get("middle_category"))
            != request.middle_category
        ):
            continue
        if (
            request.field_code
            and str(record.get("field_code") or "") != request.field_code
        ):
            continue
        if request.company_number:
            if record["stage"] == "contract":
                matched_company = any(
                    contractor.get("business_registration_number")
                    == request.company_number
                    for contractor in record["contract"]["contractors"]
                )
            elif record["stage"] == "award":
                matched_company = (
                    record["award"].get("winner_business_registration_number")
                    == request.company_number
                )
            else:
                matched_company = (
                    events.notice_to_activity.get(
                        str(record.get("bid_notice_id") or "")
                    )
                    in events.participated_activity_ids
                )
            if not matched_company:
                continue
        if request.query:
            searchable = " ".join(
                str(value or "")
                for value in (
                    record.get("notice_name"),
                    record.get("bid_notice_id"),
                    record.get("activity_id"),
                    *(award.get("winner_name") for award in record["awards"]),
                    *(
                        contractor.get("company_name")
                        for contract in record["contracts"]
                        for contractor in contract["contractors"]
                    ),
                )
            ).casefold()
            if request.query not in searchable:
                continue
        filtered_records.append(record)

    return filtered_records
