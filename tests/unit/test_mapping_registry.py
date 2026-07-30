from datetime import date
from pathlib import Path

from teoria.registry.loader import RegistryLoader
from teoria.registry.validator import RegistryValidator
from teoria.transforms.common import format_date_yyyymmdd, format_year, parse_date
from teoria.transforms.company import combine_korean_address, normalize_representative_names


REGISTRIES = Path(__file__).parents[2] / "registries"


def test_company_mapping_loads_and_references_are_valid() -> None:
    catalog = RegistryLoader(REGISTRIES).load()

    assert RegistryValidator().validate(catalog) == []
    mapping = catalog.mappings["company"]
    assert mapping.ontology == "company"
    assert "legal_entity.legal_name" in mapping.bindings
    assert "financial_fact.amount" in mapping.bindings
    corporate_number_bindings = mapping.bindings["legal_entity.corporate_registration_number"]
    assert len(corporate_number_bindings) == 14
    assert sum(".request." in rule.field for rule in corporate_number_bindings) == 7
    assert sum(".response." in rule.field for rule in corporate_number_bindings) == 7
    assert all(rule.decode is None and rule.encode is None for rule in corporate_number_bindings)
    assert len(mapping.bindings["legal_entity.representative_names"]) == 1
    assert all(
        "response.request_param" not in source
        for rules in mapping.bindings.values()
        for rule in rules
        for source in ([rule.field] if isinstance(rule.field, str) else rule.field.values())
    )


def test_mapping_transforms_execute() -> None:
    assert normalize_representative_names("전영현, 노태문, 전영현") == ["전영현", "노태문"]
    assert combine_korean_address(base_address="서울시 중구", detail_address=" 1층 ") == "서울시 중구 1층"
    assert parse_date("2026/07/30") == date(2026, 7, 30)
    assert format_date_yyyymmdd(date(2026, 7, 30)) == "20260730"
    assert format_year(2025) == "2025"


def test_reports_codec_return_type_mismatch() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    binding = catalog.mappings["company"].bindings["legal_entity.established_date"][0]
    binding.decode = "common.format_year"

    diagnostics = RegistryValidator().validate(catalog)

    assert "codec_return_type_mismatch" in {item.code for item in diagnostics}
