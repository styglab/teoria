from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.validation.registry import (
    RegistryValidator,
)
from teoria.features.semantic_modeling.registry.codecs.primitives import (
    format_date_yyyymmdd,
    format_year,
    parse_date,
)
from teoria.features.semantic_modeling.registry.codecs.legacy.company import (
    combine_korean_address,
    normalize_representative_names,
    parse_korean_tenure_years,
)


REGISTRIES = Path("backend/tests/fixtures/registry")




def test_mapping_transforms_execute() -> None:
    assert normalize_representative_names("전영현, 노태문, 전영현") == [
        "전영현",
        "노태문",
    ]
    assert (
        combine_korean_address(base_address="서울시 중구", detail_address=" 1층 ")
        == "서울시 중구 1층"
    )
    assert parse_date("2026/07/30") == date(2026, 7, 30)
    assert format_date_yyyymmdd(date(2026, 7, 30)) == "20260730"
    assert format_year(2025) == "2025"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5년 5개월", Decimal("5.416667")),
        ("5년", Decimal("5.000000")),
        ("5개월", Decimal("0.416667")),
        ("5.5", Decimal("5.5")),
        (None, None),
        ("", None),
    ],
)
def test_parse_korean_tenure_years(raw, expected) -> None:
    assert parse_korean_tenure_years(raw) == expected


def test_parse_korean_tenure_years_rejects_unsupported_text() -> None:
    with pytest.raises(ValueError, match="unsupported employee tenure value"):
        parse_korean_tenure_years("약 5년")


def test_reports_codec_return_type_mismatch() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    binding = catalog.mappings["example"].bindings["record.created_date"][0]
    binding.decode = "common.format_year"

    diagnostics = RegistryValidator().validate(catalog)

    assert "codec_return_type_mismatch" in {item.code for item in diagnostics}
