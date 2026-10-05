from pathlib import Path

from fastapi.testclient import TestClient

from teoria.admin.api import create_admin_app
from teoria.config import Settings
from teoria.metadata.models import MetadataEntity, MetadataPage, MetadataStatus, MetadataTargetRef, TableDetail
from teoria.registry.loader import RegistryLoader


REGISTRIES = Path(__file__).parents[3] / "registries"


class FakeMetadataService:
    base_url = "http://openmetadata/api"
    database_service = "teoria_postgresql"

    async def status(self):
        return MetadataStatus(enabled=True, available=True, base_url=self.base_url, database_service=self.database_service)

    async def list_services(self, **_):
        return MetadataPage(items=[_entity("service-1", "databaseService", "teoria_postgresql")], total=1)

    async def list_databases(self, **_):
        return MetadataPage(items=[_entity("database-1", "database", "teoria_data")], total=1)

    async def list_schemas(self, **_):
        return MetadataPage(items=[_entity("schema-1", "databaseSchema", "public_procurement")], total=1)

    async def list_tables(self, **_):
        return MetadataPage(items=[_entity("table-1", "table", "contracts")], total=1)

    async def get_table(self, fully_qualified_name: str):
        assert fully_qualified_name.endswith("contracts")
        return TableDetail(**_entity("table-1", "table", "contracts").model_dump(), columns=[{"name": "contract_amount"}])

    async def get_table_lineage(self, table_id: str, **_):
        return {"entity": {"id": table_id}, "nodes": []}


def _entity(entity_id: str, entity_type: str, name: str) -> MetadataEntity:
    return MetadataEntity(
        reference=MetadataTargetRef(entity_id=entity_id, entity_type=entity_type, fully_qualified_name=name),
        name=name,
    )


def test_metadata_routes_are_disabled_without_configuration() -> None:
    app = create_admin_app(settings=Settings(), catalog=RegistryLoader(REGISTRIES).load())
    client = TestClient(app)
    assert client.get("/v1/admin/metadata/status").json() == {
        "enabled": False, "available": False, "provider": "openmetadata",
        "base_url": None, "database_service": None, "reason": "openmetadata_disabled",
    }
    assert client.get("/v1/admin/metadata/tables").status_code == 503


def test_metadata_routes_expose_stable_teoria_dtos() -> None:
    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load(), metadata_service=FakeMetadataService()
    )
    client = TestClient(app)
    assert client.get("/v1/admin/metadata/status").json()["available"] is True
    tables = client.get("/v1/admin/metadata/tables").json()
    assert tables["items"][0]["reference"]["entity_type"] == "table"
    detail = client.get("/v1/admin/metadata/tables/teoria.teoria_data.public_procurement.contracts").json()
    assert detail["columns"] == [{"name": "contract_amount"}]
    lineage = client.get("/v1/admin/metadata/tables/table-1/lineage").json()
    assert lineage["entity"]["id"] == "table-1"
