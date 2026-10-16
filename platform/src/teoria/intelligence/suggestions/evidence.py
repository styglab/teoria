from __future__ import annotations

from teoria.intelligence.suggestions.execution import SuggestionApplicationError


def require_current_version(table: dict, expected: str | None) -> None:
    current = str(table.get("version")) if table.get("version") is not None else None
    if expected and current != expected:
        raise SuggestionApplicationError(
            "OpenMetadata 대상이 제안 생성 후 변경되었습니다. 제안을 다시 분석해 주세요.",
            code="stale_evidence",
        )


def require_current_column(
    table: dict,
    *,
    expected_version: str | None,
    current_description: object,
    expected_description: object,
    has_expected_description: bool,
) -> None:
    current_version = (
        str(table.get("version")) if table.get("version") is not None else None
    )
    if not expected_version or current_version == expected_version:
        return
    # OpenMetadata versions the whole table. Applying a sibling column suggestion
    # therefore advances the table version even though this column is unchanged.
    if has_expected_description and current_description == expected_description:
        return
    # Backward compatibility for suggestions created before source_description was
    # captured: an empty target is still safe to enrich after a sibling update.
    if not has_expected_description and current_description in (None, ""):
        return
    require_current_version(table, expected_version)
