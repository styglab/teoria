from __future__ import annotations

from datetime import date

from .grouping import _group_procurement_activity_records
from .models import ActivityPage
from .query import ActivityQuery


def select_activity_page(
    filtered_records: list[dict], request: ActivityQuery
) -> ActivityPage:
    if request.view_mode == "notice_grouped":
        response_records = _group_procurement_activity_records(filtered_records)
    else:
        for record in filtered_records:
            for contract in record.get("contracts") or []:
                contract.pop("_lineage_source", None)
        response_records = filtered_records
    stage_property = (
        "latest_stage" if request.view_mode == "notice_grouped" else "stage"
    )
    id_property = (
        "activity_group_id" if request.view_mode == "notice_grouped" else "activity_id"
    )
    stage_counts = {
        value: sum(item[stage_property] == value for item in response_records)
        for value in (
            "scheduled",
            "open",
            "closed",
            "award",
            "contract",
            "failed",
            "cancelled",
        )
    }
    stage_counts["all"] = len(response_records)
    linkage_counts = {
        "linked": sum(item["notice_linkage"] == "linked" for item in response_records),
        "unlinked": sum(
            item["notice_linkage"] == "unlinked" for item in response_records
        ),
    }
    filtered = (
        response_records
        if request.requested_stage == "all"
        else [
            item
            for item in response_records
            if item[stage_property] == request.requested_stage
        ]
    )
    filtered.sort(
        key=lambda item: (
            item.get("latest_activity_date") or date.min,
            str(item[id_property]),
        ),
        reverse=True,
    )
    total_items = len(filtered)
    offset = (request.page - 1) * request.page_size
    page_items = filtered[offset : offset + request.page_size]
    pagination = {
        "page": request.page,
        "page_size": request.page_size,
        "total_items": total_items,
        "total_pages": (total_items + request.page_size - 1) // request.page_size,
    }
    return ActivityPage(
        page_items,
        stage_property,
        id_property,
        stage_counts,
        linkage_counts,
        pagination,
    )
