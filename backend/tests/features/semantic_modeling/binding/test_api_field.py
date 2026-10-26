from pathlib import Path

import pytest

from teoria.features.semantic_modeling.binding.api_field import ApiFieldContractError, resolve_api_field_contract
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


ROOT = (Path(__file__).resolve().parents[5] / 'backend')


def test_api_field_binding_requires_a_verified_source_response_field() -> None:
    catalog = RegistryLoader(Path("backend/tests/fixtures/registry")).load()

    target = resolve_api_field_contract(
        catalog,
        source_id="example_api",
        operation_id="get_records",
        object_id="record",
        field_path="status",
    )

    assert target["data_type"] == "string"
    assert target["contract_version"] == "1.0.0"

    with pytest.raises(ApiFieldContractError) as exc_info:
        resolve_api_field_contract(
            catalog,
            source_id="example_api",
            operation_id="get_records",
            object_id="record",
            field_path="invented_field",
        )
    assert exc_info.value.code == "unknown_response_field"
