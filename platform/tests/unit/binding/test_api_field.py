from pathlib import Path

import pytest

from teoria.binding.api_field import ApiFieldContractError, resolve_api_field_contract
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


def test_api_field_binding_requires_a_verified_source_response_field() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()

    target = resolve_api_field_contract(
        catalog,
        source_id="nts_business_registration",
        operation_id="get_business_registration_status",
        object_id="business_status",
        field_path="b_stt_cd",
    )

    assert target["data_type"] == "string"
    assert target["contract_version"] == "1.0.0"

    with pytest.raises(ApiFieldContractError) as exc_info:
        resolve_api_field_contract(
            catalog,
            source_id="nts_business_registration",
            operation_id="get_business_registration_status",
            object_id="business_status",
            field_path="invented_field",
        )
    assert exc_info.value.code == "unknown_response_field"
