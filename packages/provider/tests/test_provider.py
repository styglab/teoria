import ast
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from teoria_provider.errors import ProviderExecutionError
from teoria_provider.executor import ProviderExecutor
from teoria_provider.html_table import extract_html_table
from teoria_provider.models import AuthenticationRequirement, PreparedRequest
from teoria_provider.models import ExecutionResponse
from teoria_provider.response_validator import ProviderResponseValidator
from teoria_provider.schema import ProviderDefinition


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "teoria_provider"


def test_extracts_configured_html_table_columns() -> None:
    html = """
    <table class="other"><tr><td>무시</td></tr></table>
    <table class="result target"><tr><th>기업명</th><th>유효기간</th></tr>
      <tr><td>테스트 기업</td><td>2026-01-01<br>~ 2026-12-31</td></tr>
    </table>
    """

    assert extract_html_table(
        html,
        table_class="target",
        columns=[{"index": 0, "field": "company_name"}, {"index": 1, "field": "period"}],
    ) == [{"company_name": "테스트 기업", "period": "2026-01-01 ~ 2026-12-31"}]


def test_provider_package_does_not_import_teoria_projects() -> None:
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "teoria" or name.startswith(("teoria.", "teoria_pipelines", "teoria_mcp")) for name in names):
                violations.append(f"{path.name}:{node.lineno}")
    assert violations == []


class TimeoutClient:
    calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, *args, **kwargs):
        self.calls += 1
        raise httpx.ReadTimeout("timed out")


@pytest.mark.asyncio
async def test_provider_executor_reports_structured_timeout() -> None:
    client = TimeoutClient()
    request = PreparedRequest(
        source_id="provider", operation_id="list_records", method="GET",
        url="https://example.test/records", idempotent=True,
        authentication=AuthenticationRequirement(type="api_key", location="query",
            name="key", environment_variable="PROVIDER_KEY"),
    )
    executor = ProviderExecutor(environment={"PROVIDER_KEY": "secret"}, max_attempts=2,
        backoff_seconds=0, client_factory=lambda **kwargs: client)

    with pytest.raises(ProviderExecutionError) as exc_info:
        await executor.execute(request)

    assert exc_info.value.code == "source_timeout"
    assert exc_info.value.attempts == 2
    assert client.calls == 2


class RateLimitedClient:
    def __init__(self) -> None:
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, *args, **kwargs):
        self.calls += 1
        request = httpx.Request("GET", "https://example.test/records")
        if self.calls == 1:
            response = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        else:
            response = httpx.Response(200, json={"items": []}, request=request)
        response.elapsed = timedelta(milliseconds=1)
        return response


@pytest.mark.asyncio
async def test_provider_executor_honors_retry_after(monkeypatch) -> None:
    client = RateLimitedClient()
    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("teoria_provider.executor.asyncio.sleep", record_sleep)
    request = PreparedRequest(
        source_id="provider", operation_id="list_records", method="GET",
        url="https://example.test/records", idempotent=True,
    )
    executor = ProviderExecutor(max_attempts=2, backoff_seconds=0.25,
        client_factory=lambda **kwargs: client)

    response = await executor.execute(request)

    assert response.status_code == 200
    assert delays == [2.0]


def test_provider_executor_parses_xml_response() -> None:
    request = httpx.Request("GET", "https://example.test/records")
    response = httpx.Response(
        200,
        headers={"content-type": "application/xml;charset=UTF-8"},
        text=(
            "<response><HeaderValueList><resultCode>00</resultCode></HeaderValueList>"
            "<body><items><item><certSeCode>03</certSeCode></item></items></body>"
            "<totalCount>1</totalCount></response>"
        ),
        request=request,
    )
    response.elapsed = timedelta(milliseconds=1)

    execution = ProviderExecutor._execution_response(response)

    assert execution.content_type == "application/xml"
    assert execution.body == {
        "response": {
            "HeaderValueList": {"resultCode": "00"},
            "body": {"items": {"item": {"certSeCode": "03"}}},
            "totalCount": "1",
        }
    }


def test_response_validator_accepts_omitted_records_only_when_total_is_zero() -> None:
    definition = ProviderDefinition.model_validate({
        "id": "provider",
        "provider": {"organization": "Provider"},
        "type": "api",
        "specification": {"format": "openapi", "version": "3.0"},
        "access": {"base_url": "https://example.test"},
        "components": {"objects": [{
            "id": "record",
            "fields": [{"id": "recordId", "data_type": "string"}],
        }]},
        "operations": [{
            "id": "list_records",
            "method": "GET",
            "path": "/records",
            "pagination": {
                "type": "page_number",
                "page": {"request": "query.page"},
                "page_size": {"request": "query.size"},
                "total_count": "body.totalCount",
            },
            "response": {
                "content_type": "application/json",
                "http_status": 200,
                "data": {
                    "record_path": "body.items[]",
                    "ref": "record",
                },
            },
        }],
    })
    empty = ExecutionResponse(
        status_code=200, content_type="application/json", headers={},
        body={"body": {"totalCount": 0}}, elapsed_ms=1,
    )
    non_empty = ExecutionResponse(
        status_code=200, content_type="application/json", headers={},
        body={"body": {"totalCount": 1}}, elapsed_ms=1,
    )

    validator = ProviderResponseValidator()
    assert validator.validate(definition, "list_records", empty) == []
    assert validator.validate(definition, "list_records", non_empty)[0].code == "record_path_not_found"
