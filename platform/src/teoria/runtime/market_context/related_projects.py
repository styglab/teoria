"""Filtering, ordering, and pagination policy for related contract projects."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


SUPPORTED_PROJECT_FILTERS = (
    "similar_amount",
    "entry_or_reentering_supplier",
    "repeat_supplier",
)


@dataclass(frozen=True)
class RelatedProjectQuery:
    filters: tuple[str, ...] = ()
    filters_supplied: bool = False
    operator: str = "and"
    sort: str = "recent_desc"
    page: int = 1
    page_size: int = 20

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> "RelatedProjectQuery":
        supplied = "project_filters" in inputs
        filters = tuple(dict.fromkeys(
            str(value) for value in inputs.get("project_filters", [])))
        return cls(
            filters=filters,
            filters_supplied=supplied,
            operator=str(inputs.get("filter_operator", "and")),
            sort=str(inputs.get("sort", "recent_desc")),
            page=int(inputs.get("page", 1)),
            page_size=int(inputs.get("page_size", 20)),
        )


def filter_and_page_related_projects(
    items: list[dict[str, Any]], query: RelatedProjectQuery, *,
    reference_amount: Decimal | None,
) -> dict[str, Any]:
    """Apply filters to unique contract events before sorting and pagination."""
    filter_counts = {key: sum(key in item["matched_filters"] for item in items)
        for key in SUPPORTED_PROJECT_FILTERS}
    filter_counts = {"all": len(items), **filter_counts}

    filtered = items
    if query.filters_supplied and query.filters:
        predicate = all if query.operator == "and" else any
        filtered = [item for item in filtered if predicate(
            value in item["matched_filters"] for value in query.filters)]

    if query.sort == "amount_desc":
        filtered.sort(key=lambda item: (
            -(item["contract_amount"] or 0), item["contract_event_id"]))
    elif query.sort == "amount_similarity" and reference_amount:
        filtered.sort(key=lambda item: (
            abs(Decimal(str(item["contract_amount"] or 0)) - reference_amount),
            -item["contract_date"].toordinal()))
    else:
        filtered.sort(key=lambda item: (
            item["contract_date"], item["contract_event_id"]), reverse=True)

    total = len(filtered)
    offset = (query.page - 1) * query.page_size
    page_items = filtered[offset:offset + query.page_size]
    for item in page_items:
        item["matched_filters"] = sorted(item["matched_filters"])
        item["is_repeat_supplier"] = bool(item["repeat_suppliers"])

    applied_filters = list(query.filters)
    return {
        "items": page_items,
        "filter_counts": filter_counts,
        "applied_filter": {"filters": applied_filters,
            "operator": query.operator if query.filters_supplied else "and",
            "total_items": total},
        "pagination": {"page": query.page, "page_size": query.page_size,
            "total_items": total,
            "total_pages": (total + query.page_size - 1) // query.page_size},
    }
