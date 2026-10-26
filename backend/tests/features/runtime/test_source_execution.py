from pathlib import Path
from datetime import timedelta

import pytest
import httpx

from teoria.integrations.provider_api.errors import ProviderExecutionError
from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.models import ExecutionResponse
from teoria.features.semantic_modeling.registry.source_request_builder import (
    RequestBuildError,
    SourceRequestBuilder,
)
from teoria.features.semantic_modeling.registry.source_response_validator import (
    SourceResponseValidator,
)
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


ROOT = Path(__file__).resolve().parents[4] / "backend"


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


class TimeoutClient(RetryClient):
    async def request(self, *args, **kwargs):
        self.calls += 1
        raise httpx.ReadTimeout("timed out")


def test_builds_request_from_source_registry() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()
    request = SourceRequestBuilder().build(
        catalog,
        "example_api",
        "get_records",
        {"body": {"codes": ["0000000000"]}},
    )

    assert request.method == "POST"
    assert request.url.endswith("/records")
    assert request.query == {"format": "JSON"}
    assert request.body == {"codes": ["0000000000"]}
    assert request.authentication is not None
    assert (
        request.authentication.environment_variable
        == "TEORIA_SOURCE_EXAMPLE_API_API_KEY"
    )


def test_rejects_invalid_operation_input() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()

    with pytest.raises(RequestBuildError) as exc_info:
        SourceRequestBuilder().build(
            catalog,
            "example_api",
            "get_records",
            {"body": {"codes": ["invalid"]}},
        )

    assert {item.code for item in exc_info.value.diagnostics} == {
        "input_data_type_mismatch"
    }


def test_database_source_cannot_be_built_as_an_http_request() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()

    with pytest.raises(RequestBuildError) as exc_info:
        SourceRequestBuilder().build(
            catalog, "example_data", "records", {}
        )

    assert exc_info.value.diagnostics[0].code == "unsupported_source_operation"


@pytest.mark.asyncio
async def test_retries_idempotent_source_request_on_temporary_failure() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()
    request = SourceRequestBuilder().build(
        catalog,
        "example_api",
        "get_records",
        {"body": {"codes": ["0000000000"]}},
    )
    client = RetryClient(
        [
            FakeHTTPResponse(503, {"error": "temporary"}),
            FakeHTTPResponse(200, {"status_code": "OK", "data": []}),
        ]
    )
    executor = ProviderExecutor(
        environment={"TEORIA_SOURCE_EXAMPLE_API_API_KEY": "secret"},
        backoff_seconds=0,
        client_factory=lambda **kwargs: client,
    )

    response = await executor.execute(request)

    assert request.idempotent is True
    assert response.status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_reports_structured_source_timeout_after_retries() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()
    request = SourceRequestBuilder().build(
        catalog,
        "example_api",
        "get_records",
        {"body": {"codes": ["0000000000"]}},
    )
    client = TimeoutClient([])
    executor = ProviderExecutor(
        environment={"TEORIA_SOURCE_EXAMPLE_API_API_KEY": "secret"},
        max_attempts=2,
        backoff_seconds=0,
        client_factory=lambda **kwargs: client,
    )

    with pytest.raises(ProviderExecutionError) as exc_info:
        await executor.execute(request)

    assert exc_info.value.to_dict() == {
        "code": "source_timeout",
        "message": "source request timed out after 2 attempt(s)",
        "source": "example_api",
        "operation": "get_records",
        "attempts": 2,
        "retryable": True,
        "http_status": None,
    }
    assert client.calls == 2






def test_rejects_failed_source_control_code() -> None:
    catalog = RegistryLoader(
        Path("backend/tests/fixtures/registry")
    ).load()
    response = ExecutionResponse(
        status_code=200,
        content_type="application/json",
        headers={},
        body={"status_code": "ERROR", "data": []},
        elapsed_ms=1.0,
    )

    diagnostics = SourceResponseValidator().validate(
        catalog,
        "example_api",
        "get_records",
        response,
    )

    assert [item.code for item in diagnostics] == ["source_operation_failed"]


def test_nested_reference_preserves_empty_optional_value_and_rejects_invalid_code():
    catalog = RegistryLoader(Path("backend/tests/fixtures/registry")).load()
    request = SourceRequestBuilder().build(catalog, "example_api", "verify_records", {
        "body": {"records": [{"code": "0000000000", "optional_code": ""}]}})
    assert request.body["records"][0]["optional_code"] == ""
    response = ExecutionResponse(status_code=200, content_type="application/json", headers={},
        body={"data": [{"request_param": {"code": "0000000000", "optional_code": "invalid"}}]}, elapsed_ms=1.0)
    diagnostics = SourceResponseValidator().validate(catalog, "example_api", "verify_records", response)
    assert [d.code for d in diagnostics] == ["response_data_type_mismatch"]
    assert diagnostics[0].location.endswith("request_param.optional_code")
