from pathlib import Path
from datetime import date
from uuid import uuid4

import pytest

from teoria_provider_api.models import ExecutionResponse
from teoria_pipelines.connectors import PPSContractClient
from teoria_pipelines.connectors.pps_contracts import ConnectorResponseError
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow


PIPELINES = Path(__file__).parents[2]


class FakeExecutor:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        page = request.query["pageNo"]
        return ExecutionResponse(
            status_code=200,
            content_type="application/json",
            headers={},
            body={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "OK"},
                    "body": {
                        "items": [{"untyCntrctNo": f"contract-{page}"}],
                        "totalCount": 2,
                    },
                }
            },
            elapsed_ms=1,
        )


@pytest.mark.asyncio
async def test_fetches_all_pages_and_builds_raw_provenance() -> None:
    catalog = PipelineLoader(PIPELINES).load()
    registry = catalog.connectors["pps_contract_api"]
    executor = FakeExecutor()
    client = PPSContractClient(
        registry.connector,
        path=catalog.connector_paths["pps_contract_api"],
        executor=executor,
        page_size=1,
    )

    batch = await client.fetch_window(
        uuid4(),
        CollectionWindow(date(2026, 7, 1), date(2026, 7, 1)),
        ["list_goods_contracts"],
    )

    assert batch.pages == 2
    assert len(batch.records) == 2
    assert [request.query["pageNo"] for request in executor.requests] == [1, 2]
    assert all(len(record.source_record_hash) == 64 for record in batch.records)


@pytest.mark.asyncio
async def test_reports_provider_error_envelope_before_contract_validation() -> None:
    class ErrorExecutor:
        async def execute(self, request):
            return ExecutionResponse(
                status_code=200, content_type="application/json", headers={},
                body={"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
                    "returnReasonCode": "22", "returnAuthMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
                }}}, elapsed_ms=1,
            )

    catalog = PipelineLoader(PIPELINES).load()
    registry = catalog.connectors["pps_contract_api"]
    client = PPSContractClient(
        registry.connector, path=catalog.connector_paths["pps_contract_api"],
        executor=ErrorExecutor(),
    )

    with pytest.raises(ConnectorResponseError, match="provider_error code=22"):
        await client.fetch_operation(
            uuid4(), CollectionWindow(date(2021, 7, 1), date(2021, 7, 1)),
            "list_service_contracts",
        )


@pytest.mark.asyncio
async def test_reports_provider_namespaced_error_envelope() -> None:
    class ErrorExecutor:
        async def execute(self, request):
            return ExecutionResponse(
                status_code=200, content_type="application/json", headers={},
                body={"nkoneps.com.response.ResponseError": {"header": {
                    "resultCode": "99", "resultMsg": "기타 에러",
                }}}, elapsed_ms=1,
            )

    catalog = PipelineLoader(PIPELINES).load()
    registry = catalog.connectors["pps_contract_api"]
    client = PPSContractClient(
        registry.connector, path=catalog.connector_paths["pps_contract_api"],
        executor=ErrorExecutor(),
    )

    with pytest.raises(ConnectorResponseError, match="provider_error code=99 message=기타 에러"):
        await client.fetch_operation(
            uuid4(), CollectionWindow(date(2021, 7, 29), date(2021, 7, 29)),
            "list_service_contracts",
        )


@pytest.mark.asyncio
async def test_retries_code_99_response_on_the_same_page() -> None:
    class RecoveringExecutor:
        def __init__(self):
            self.calls = 0

        async def execute(self, request):
            self.calls += 1
            body = (
                {"nkoneps.com.response.ResponseError": {"header": {
                    "resultCode": "99", "resultMsg": "기타 에러",
                }}}
                if self.calls == 1
                else {"response": {
                    "header": {"resultCode": "00", "resultMsg": "OK"},
                    "body": {"items": [{"untyCntrctNo": "recovered"}], "totalCount": 1},
                }}
            )
            return ExecutionResponse(
                status_code=200, content_type="application/json", headers={},
                body=body, elapsed_ms=1,
            )

    catalog = PipelineLoader(PIPELINES).load()
    registry = catalog.connectors["pps_contract_api"]
    executor = RecoveringExecutor()
    client = PPSContractClient(
        registry.connector, path=catalog.connector_paths["pps_contract_api"],
        executor=executor, provider_error_max_attempts=2,
        provider_error_backoff_seconds=0,
    )

    batch = await client.fetch_operation(
        uuid4(), CollectionWindow(date(2021, 7, 29), date(2021, 7, 29)),
        "list_service_contracts",
    )

    assert executor.calls == 2
    assert len(batch.records) == 1
