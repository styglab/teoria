from pathlib import Path
from datetime import timedelta

import pytest
import httpx

from teoria.execution.source.models import ExecutionResponse
from teoria.execution.source.executor import SourceExecutor
from teoria.execution.source.request_builder import RequestBuildError, SourceRequestBuilder
from teoria.execution.source.response_validator import SourceResponseValidator
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[2]


class FakeHTTPResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._body = body
        self.text = ""
        self.elapsed = timedelta(milliseconds=1)

    def json(self):
        return self._body


class RetryClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, *args, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


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

    assert {item.code for item in exc_info.value.diagnostics} == {"input_data_type_mismatch"}


@pytest.mark.asyncio
async def test_retries_idempotent_source_request_on_temporary_failure() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    request = SourceRequestBuilder().build(
        catalog,
        "nts_business_registration",
        "get_business_registration_status",
        {"body": {"b_no": ["0000000000"]}},
    )
    client = RetryClient(
        [
            FakeHTTPResponse(503, {"error": "temporary"}),
            FakeHTTPResponse(200, {"status_code": "OK", "data": []}),
        ]
    )
    executor = SourceExecutor(
        environment={"NTS_BUSINESS_REGISTRATION_SERVICEKEY": "secret"},
        backoff_seconds=0,
        client_factory=lambda **kwargs: client,
    )

    response = await executor.execute(request)

    assert request.idempotent is True
    assert response.status_code == 200
    assert client.calls == 2


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


def test_recursively_validates_nested_response_refs() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    response = ExecutionResponse(
        status_code=200,
        content_type="application/json",
        headers={},
        body={
            "status_code": "OK",
            "request_cnt": 1,
            "valid_cnt": 1,
            "data": [
                {
                    "b_no": "0000000000",
                    "valid": "01",
                    "valid_msg": "확인",
                    "request_param": {
                        "b_no": "0000000000",
                        "start_dt": "20200101",
                        "p_nm": "홍길동",
                        "corp_no": "invalid",
                    },
                    "status": {"b_no": "0000000000", "b_stt_cd": "01", "tax_type_cd": "01"},
                }
            ]
        },
        elapsed_ms=1.0,
    )

    diagnostics = SourceResponseValidator().validate(
        catalog,
        "nts_business_registration",
        "verify_business_registration",
        response,
    )

    assert [item.code for item in diagnostics] == ["response_data_type_mismatch"]
    assert diagnostics[0].location.endswith("request_param.corp_no")


def test_rejects_failed_source_control_code() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    response = ExecutionResponse(
        status_code=200,
        content_type="application/json",
        headers={},
        body={"status_code": "ERROR", "data": []},
        elapsed_ms=1.0,
    )

    diagnostics = SourceResponseValidator().validate(
        catalog,
        "nts_business_registration",
        "get_business_registration_status",
        response,
    )

    assert [item.code for item in diagnostics] == ["source_operation_failed"]
