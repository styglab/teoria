from pathlib import Path

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.runtime.capability.binder import CapabilityBinder
from teoria.features.runtime.capability.runner import CapabilityRunner
from teoria.features.runtime.source.database import DatabaseQueryResult

REGISTRIES = Path("backend/tests/fixtures/registry")

async def test_database_query_materializes_identities_links_and_pagination():
    class Database:
        async def execute(self, catalog, source, relation, query):
            assert (source, relation) == ("example_data", "records")
            assert query["filters"] == [{"field": "created_date", "operator": "gte", "value": "2026-01-01"}]
            assert query["pagination"] == {"page": 2, "page_size": 5, "root_field": "record_id"}
            return DatabaseQueryResult([{"record_id": "r1", "name": "Record", "group_id": "g1"}],
                                       {"page": 2, "page_size": 5, "total_items": 6, "total_pages": 2})
    catalog = RegistryLoader(REGISTRIES).load()
    result = await CapabilityRunner(database_executor=Database()).run(
        catalog, "search_records", {"from_date": "2026-01-01", "page": 2, "page_size": 5})
    assert {o.object_type for o in result.objects} == {"record", "group"}
    record = next(o for o in result.objects if o.object_type == "record")
    group = next(o for o in result.objects if o.object_type == "group")
    assert record.properties["record_id"] == "r1"
    assert result.links[0].source_object_id == record.object_id
    assert result.links[0].target_object_id == group.object_id
    assert result.pagination["total_items"] == 6


def test_binder_resolves_defaults_and_property_bindings():
    catalog = RegistryLoader(REGISTRIES).load()
    binder = CapabilityBinder()
    capability = catalog.capabilities["search_records"]
    query = binder.bind(catalog, capability, capability.steps[0], {"from_date": "2026-01-01"})
    assert query["pagination"] == {"page": 1, "page_size": 20, "root_field": "record_id"}
    capability = catalog.capabilities["get_record"]
    assert binder.bind(catalog, capability, capability.steps[0], {"record_id": "r1"}) == {
        "filters": [{"field": "record_id", "operator": "eq", "value": "r1"}]}
