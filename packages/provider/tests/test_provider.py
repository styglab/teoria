import ast
from pathlib import Path

import httpx
import pytest

from teoria_provider.errors import ProviderExecutionError
from teoria_provider.executor import ProviderExecutor
from teoria_provider.models import AuthenticationRequirement, PreparedRequest
from teoria_provider.models import ExecutionResponse
from teoria_provider.response_validator import ProviderResponseValidator
from teoria_provider.schema import ProviderDefinition


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "teoria_provider"


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
