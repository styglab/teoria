from pathlib import Path

import pytest

from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.validator import PipelineValidator
from teoria_pipelines.verification import verify_connector


PIPELINES = Path(__file__).parents[2]
def _catalog():
    return PipelineLoader(PIPELINES).load()


def test_pps_contract_api_connector_is_complete_and_valid() -> None:
    pipeline_catalog = _catalog()
    registry = pipeline_catalog.connectors["pps_contract_api"]
    operations = {operation.id: operation for operation in registry.connector.operations}

    assert PipelineValidator().validate(
        pipeline_catalog,
        connector_id="pps_contract_api",
    ) == []
    assert set(operations) == {
        "list_goods_contracts",
        "list_construction_contracts",
        "list_service_contracts",
        "list_foreign_procurement_contracts",
    }
    assert [len(item.fields) for item in registry.connector.components.objects] == [39, 43, 42, 35]
    assert all(operation.pagination is not None for operation in operations.values())
    assert all(operation.request is not None for operation in operations.values())
    assert all(
        next(field for field in operation.request.query.fields if field.id == "type").default == "json"
        for operation in operations.values()
    )
    assert all(operation.response.data.record_path == "response.body.items[]" for operation in operations.values())
    assert all(operation.response.control is not None for operation in operations.values())


def test_pps_reference_is_active_and_uses_the_source_document() -> None:
    pipeline_catalog = _catalog()
    reference = pipeline_catalog.references["pps_contract_api"]
    source_document = pipeline_catalog.connectors["pps_contract_api"].connector.specification.source_document

    assert reference.status == "active"
    assert reference.target == "connector"
    assert source_document in {item.path for item in reference.files}


def test_procurement_pipeline_contract_is_self_consistent() -> None:
    pipeline_catalog = _catalog()
    pipeline = pipeline_catalog.pipelines["pps_contract_ingestion"]

    assert PipelineValidator().validate(pipeline_catalog) == []
    assert pipeline.connector == "pps_contract_api"
    assert pipeline.sink.source == "teoria_public_procurement"
    assert set(pipeline.sink.relations) == {"contracts", "contract_suppliers", "public_organizations", "contract_demand_organizations"}


@pytest.mark.asyncio
async def test_ingestion_connector_build_verification() -> None:
    pipeline_catalog = _catalog()
    result = await verify_connector(
        pipeline_catalog,
        connector_id="pps_contract_api",
        operation_id="list_goods_contracts",
        profile="build",
        input_data={
            "query": {
                "numOfRows": 10,
                "pageNo": 1,
                "inqryDiv": "1",
                "inqryBgnDate": "20160830",
                "inqryEndDate": "20160831",
            }
        },
    )

    assert result["status"] == "passed"
    assert result["prepared_request"]["query"]["type"] == "json"
    assert result["prepared_request"]["authentication"]["environment_variable"] == (
        "TEORIA_CONNECTOR_PPS_CONTRACT_API_KEY"
    )
