"""Execution must honor namespace, lifecycle, time and source ordering contracts."""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from teoria.settings import Settings
from teoria.entrypoints.runtime_api import create_runtime_app
from teoria.platform.ontology.contracts.loader import RegistryLoader
from teoria.platform.ontology.contracts.schema.common import FieldDefinition
from teoria.platform.ontology.runtime.capability.runner import CapabilityRunner
from teoria.platform.ontology.runtime.capability.handlers import CapabilityHandlers
from teoria.platform.ontology.runtime.capability.contracts import (
    CapabilityResult,
    CapabilityExecutionError,
)

ROOT = Path("backend/tests/fixtures/registry")


class Database:
    async def execute(self, *args):
        return [
            {"record_id": "r1", "name": "old", "group_id": "g1", "revision": 9},
            {"record_id": "r1", "name": "new", "group_id": "g1", "revision": 10},
        ]


async def test_same_named_objects_and_links_in_another_namespace_are_not_returned():
    catalog = RegistryLoader(ROOT).load()
    catalog.runtime_contracts["shadow"] = catalog.runtime_contracts[
        "example"
    ].model_copy(update={"id": "shadow"}, deep=True)
    catalog.mappings["shadow"] = catalog.mappings["example"].model_copy(
        update={"id": "shadow", "ontology": "shadow"}, deep=True
    )
    result = await CapabilityRunner(database_executor=Database()).run(
        catalog, "search_records", {"from_date": "2026-01-01"}
    )
    assert result.objects and result.links
    assert {o.ontology for o in result.objects} == {"example"}
    assert {link.ontology for link in result.links} == {"example"}


@pytest.mark.parametrize("status", ["draft", "validated", "retired"])
async def test_non_active_capability_is_neither_discoverable_nor_executable(status):
    catalog = RegistryLoader(ROOT).load()
    catalog.capabilities["search_records"].lifecycle.status = status
    runner = CapabilityRunner(database_executor=Database())
    with pytest.raises(CapabilityExecutionError, match="is " + status):
        await runner.run(catalog, "search_records", {"from_date": "2026-01-01"})
    client = TestClient(
        create_runtime_app(
            settings=Settings(runtime_api_token="test"), catalog=catalog, runner=runner
        )
    )
    headers = {"Authorization": "Bearer test"}
    assert not client.get("/v1/capabilities", headers=headers).json()["capabilities"]
    response = client.post(
        "/v1/capabilities/search_records:execute",
        headers=headers,
        json={"inputs": {"from_date": "2026-01-01"}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "inactive_capability"


async def test_capability_deadline_is_stricter_than_global_deadline():
    catalog = RegistryLoader(ROOT).load()
    cap = catalog.capabilities["search_records"]
    cap.kind = "compute"
    cap.processor = "example.compute"
    cap.policy.timeout_seconds = 0.01
    handlers = CapabilityHandlers()
    cancelled = asyncio.Event()

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    handlers.register_processor("example.compute", stalled)
    with pytest.raises(CapabilityExecutionError) as exc:
        await CapabilityRunner(handlers=handlers, timeout_seconds=1).run(
            catalog, "search_records", {}
        )
    assert exc.value.code == "capability_timeout"
    assert cancelled.is_set()


async def test_numeric_revision_ten_wins_over_nine_across_decoder_and_materializer():
    catalog = RegistryLoader(ROOT).load()
    catalog.sources["example_data"].source.relations[0].fields.append(
        FieldDefinition(id="revision", name="Revision", data_type="integer")
    )
    catalog.mappings["example"].materializations[
        "example_data.records"
    ].record_order = "revision"
    result = await CapabilityRunner(database_executor=Database()).run(
        catalog, "search_records", {"from_date": "2026-01-01"}
    )
    assert (
        next(o for o in result.objects if o.object_type == "record").properties["name"]
        == "new"
    )
