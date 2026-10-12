from __future__ import annotations

from typing import Any

from ..sql import (
    _PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY,
)


def _enrich_procurement_classification(
    connection: Any, rows: list[dict[str, Any]],
) -> None:
    """Apply the same provider-backed hierarchy fallback to activity rows."""
    missing_codes = sorted({
        str(row["procurement_classification_number"])
        for row in rows
        if row.get("procurement_classification_number")
        and not row.get("procurement_large_classification_name")
        and not row.get("procurement_middle_classification_name")
    })
    if missing_codes:
        hierarchy = {
            str(row["procurement_classification_number"]): dict(row)
            for row in connection.execute(
                _PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY,
                {"classification_numbers": missing_codes},
            ).fetchall()
        }
        for row in rows:
            item = hierarchy.get(str(row.get("procurement_classification_number") or ""))
            if not item:
                continue
            for key in (
                "procurement_large_classification_name",
                "procurement_middle_classification_name", "purchase_items",
            ):
                if not row.get(key):
                    row[key] = item.get(key)
    notice_fields = {
        str(row["bid_notice_id"]): row for row in rows
        if row.get("procurement_classification_number")
    }
    for row in rows:
        if row.get("procurement_classification_number"):
            continue
        field = notice_fields.get(str(row.get("bid_notice_id") or ""))
        if not field:
            continue
        for key in (
            "procurement_classification_number",
            "procurement_classification_name",
            "procurement_large_classification_name",
            "procurement_middle_classification_name", "purchase_items",
        ):
            row[key] = field.get(key)
