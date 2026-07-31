from pathlib import Path
from datetime import date
from uuid import uuid4

import pytest

from teoria_provider.models import ExecutionResponse
from teoria_pipelines.connectors import PPSContractClient
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
