from __future__ import annotations

from typing import Any

from teoria.domains.public_procurement.classification import field_identity, normalize_category


def _normalized_category(value: Any) -> str | None:
    return normalize_category(value)


def _effective_large_category(row: dict[str, Any]) -> str | None:
    if str(row.get("work_type") or "") == "construction":
        return _normalized_category(row.get("procurement_classification_name"))
    return _normalized_category(row.get("procurement_large_classification_name"))


def _effective_middle_category(row: dict[str, Any]) -> str | None:
    if str(row.get("work_type") or "") == "construction":
        return None
    return _normalized_category(row.get("procurement_middle_classification_name"))


def _procurement_field_identity(row: dict[str, Any]) -> dict[str, Any] | None:
    if any(row.get(key) for key in ("field_code", "field_name", "large_category")):
        normalized = dict(row)
        for source, target in (
            ("field_code", "procurement_classification_number"),
            ("field_name", "procurement_classification_name"),
            ("large_category", "procurement_large_classification_name"),
            ("middle_category", "procurement_middle_classification_name"),
        ):
            if not normalized.get(target):
                normalized[target] = normalized.get(source)
        return field_identity(normalized)
    return field_identity(row)
