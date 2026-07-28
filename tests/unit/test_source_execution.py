from pathlib import Path

import pytest

from teoria.execution.source.request_builder import RequestBuildError, SourceRequestBuilder
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[2]


def test_builds_request_from_source_registry() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    request = SourceRequestBuilder().build(
        catalog,
        "nts_business_registration",
        "get_business_registration_status",
        {"body": {"b_no": ["0000000000"]}},
    )

    assert request.method == "POST"
    assert request.url.endswith("/status")
    assert request.query == {"returnType": "JSON"}
    assert request.body == {"b_no": ["0000000000"]}
    assert request.authentication is not None
    assert request.authentication.environment_variable == "NTS_BUSINESS_REGISTRATION_SERVICEKEY"


def test_rejects_invalid_operation_input() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()

    with pytest.raises(RequestBuildError) as exc_info:
        SourceRequestBuilder().build(
            catalog,
            "nts_business_registration",
            "get_business_registration_status",
            {"body": {"b_no": ["invalid"]}},
        )

    assert {item.code for item in exc_info.value.diagnostics} == {"input_format_mismatch"}


def test_allows_empty_optional_source_field() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    request = SourceRequestBuilder().build(
        catalog,
        "nts_business_registration",
        "verify_business_registration",
        {
            "body": {
                "businesses": [
                    {
                        "b_no": "0000000000",
                        "start_dt": "20000101",
                        "p_nm": "홍길동",
                        "corp_no": "",
                    }
                ]
            }
        },
    )

    assert request.body["businesses"][0]["corp_no"] == ""
