from __future__ import annotations

from typing import Any


def normalize_category(value: Any) -> str | None:
    normalized = " ".join(str(value or "").split())
    return normalized or None


def field_identity(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return one provider-backed field identity for a procurement event.

    ``work_type`` is intentionally not used as a field category.  For goods
    notices whose only official classification is a purchase item, that item
    is exposed as the first available field level instead of manufacturing a
    ``물품`` category.
    """
    code = str(row.get("procurement_classification_number") or "").strip()
    name = str(row.get("procurement_classification_name") or "").strip()
    purchase_items = [
        item for item in (row.get("purchase_items") or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    ]
    if not code and str(row.get("work_type") or "") == "goods" and purchase_items:
        indexed_items = list(enumerate(purchase_items))

        def purchase_item_order(value: tuple[int, dict[str, Any]]) -> tuple[int, int]:
            index, item = value
            digits = "".join(
                character for character in str(item.get("sequence") or "")
                if character.isdigit()
            )
            return (int(digits) if digits else 2_147_483_647, index)

        _, primary_item = min(indexed_items, key=purchase_item_order)
        code = str(primary_item.get("code") or "").strip()
        name = str(primary_item.get("name") or "").strip().strip("[]").strip()
        return {
            "code": code,
            "name": name or None,
            "large_category": None,
            "middle_category": None,
            "detailed_items": purchase_items,
            "source": "purchase_item",
        }
    if not code and not name:
        return None
    is_construction = str(row.get("work_type") or "") == "construction"
    return {
        "code": code or f"name:{name}",
        "name": name or None,
        "large_category": name if is_construction else normalize_category(
            row.get("procurement_large_classification_name")
        ),
        "middle_category": None if is_construction else normalize_category(
            row.get("procurement_middle_classification_name")
        ),
        "detailed_items": row.get("purchase_items") or [],
        "source": (
            "construction_work_category" if is_construction
            else "procurement_classification"
        ),
    }


def decorate_field_distribution(
    items: list[dict[str, Any]], *, level: str, work_type: str | None,
    large_category: str | None, middle_category: str | None,
) -> list[dict[str, Any]]:
    """Add an explicit, frontend-independent drill-down contract."""
    decorated = []
    for source_item in items:
        item = dict(source_item)
        is_unclassified = item.get("classification_source") == "unclassified"
        if is_unclassified:
            display_level = "unclassified"
            display_code = None
            display_name = "미분류"
            has_children = False
        elif level in {"large", "middle"}:
            property_name = "large_category" if level == "large" else "middle_category"
            display_level = property_name
            display_name = normalize_category(item.get(property_name))
            display_code = display_name
            has_children = True
        else:
            display_level = "field_code"
            display_code = item.get("field_code")
            display_name = item.get("field_name")
            has_children = (
                bool(item.get("detailed_items"))
                and item.get("classification_source") != "purchase_item"
                and level != "detail"
            )

        selection_filter: dict[str, Any] = {}
        selected_work_type = work_type
        item_work_types = list(item.get("work_types") or [])
        if selected_work_type is None and len(item_work_types) == 1:
            selected_work_type = item_work_types[0]
        if selected_work_type:
            selection_filter["work_type"] = selected_work_type
        if is_unclassified:
            selection_filter["large_category"] = "미분류"
        else:
            selected_large = large_category or item.get("large_category")
            selected_middle = middle_category or item.get("middle_category")
            if selected_large:
                selection_filter["large_category"] = selected_large
            if selected_middle:
                selection_filter["middle_category"] = selected_middle
            if display_level == "field_code" and item.get("field_code"):
                selection_filter["field_code"] = item["field_code"]

        item.update({
            "display_level": display_level,
            "display_code": display_code,
            "display_name": display_name,
            "has_children": has_children,
            "selection_filter": selection_filter,
        })
        decorated.append(item)
    return decorated
