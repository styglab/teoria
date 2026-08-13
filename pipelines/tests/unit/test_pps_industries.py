import pytest

from teoria_pipelines.persistence.postgres import _validate_industry_snapshot


def _row(code: str) -> dict:
    return {
        "industry_code": code,
        "industry_name": f"업종 {code}",
        "classification_code": "99",
        "classification_name": "기타",
        "source_registered_at": "2026-01-01 00:00",
    }


def test_industry_snapshot_rejects_duplicates_and_large_drop() -> None:
    with pytest.raises(ValueError, match="duplicate_industry_code"):
        _validate_industry_snapshot([_row("1468"), _row("1468")], 2)
    with pytest.raises(ValueError, match="dropped_over_10_percent"):
        _validate_industry_snapshot([_row(str(index)) for index in range(89)], 100)


def test_industry_snapshot_accepts_complete_unique_snapshot() -> None:
    _validate_industry_snapshot([_row(str(index)) for index in range(90)], 100)
