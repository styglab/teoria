from pathlib import Path

from fastapi.testclient import TestClient

from teoria.admin.api import create_admin_app
from teoria.settings import Settings
from teoria.metadata.models import (
    MetadataEntity,
    MetadataPage,
    MetadataStatus,
    MetadataTargetRef,
    TableDetail,
)
from teoria.registry.loader import RegistryLoader


REGISTRIES = Path(__file__).parents[3] / "registries"


class FakeMetadataService:
    base_url = "http://openmetadata/api"
    database_service = "teoria_postgresql"

    async def status(self):
        return MetadataStatus(
            enabled=True,
            available=True,
            base_url=self.base_url,
            database_service=self.database_service,
        )

    async def list_services(self, **_):
        return MetadataPage(
            items=[_entity("service-1", "databaseService", "teoria_postgresql")],
            total=1,
        )

    async def list_databases(self, **_):
        return MetadataPage(
            items=[_entity("database-1", "database", "teoria_data")], total=1
        )

    async def list_schemas(self, **_):
        return MetadataPage(
            items=[_entity("schema-1", "databaseSchema", "public_procurement")], total=1
        )

    async def list_tables(self, **_):
        return MetadataPage(items=[_entity("table-1", "table", "contracts")], total=1)

    async def get_table(self, fully_qualified_name: str):
        assert fully_qualified_name.endswith("contracts")
        return TableDetail(
            **_entity("table-1", "table", "contracts").model_dump(),
            columns=[{"name": "contract_amount"}],
        )

    async def get_table_lineage(self, table_id: str, **_):
        return {"entity": {"id": table_id}, "nodes": []}


def _entity(entity_id: str, entity_type: str, name: str) -> MetadataEntity:
    return MetadataEntity(
        reference=MetadataTargetRef(
            entity_id=entity_id, entity_type=entity_type, fully_qualified_name=name
        ),
        name=name,
    )


def test_metadata_routes_are_disabled_without_configuration() -> None:
    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load()
    )
    client = TestClient(app)
    assert client.get("/v1/admin/metadata/status").json() == {
        "enabled": False,
        "available": False,
        "provider": "openmetadata",
        "base_url": None,
        "database_service": None,
        "reason": "openmetadata_disabled",
    }
    assert client.get("/v1/admin/metadata/tables").status_code == 503


def test_metadata_routes_expose_stable_teoria_dtos() -> None:
    app = create_admin_app(
        settings=Settings(),
        catalog=RegistryLoader(REGISTRIES).load(),
        metadata_service=FakeMetadataService(),
    )
    client = TestClient(app)
    assert client.get("/v1/admin/metadata/status").json()["available"] is True
    tables = client.get("/v1/admin/metadata/tables").json()
    assert tables["items"][0]["reference"]["entity_type"] == "table"
    detail = client.get(
        "/v1/admin/metadata/tables/teoria.teoria_data.public_procurement.contracts"
    ).json()
    assert detail["columns"] == [{"name": "contract_amount"}]
    lineage = client.get("/v1/admin/metadata/tables/table-1/lineage").json()
    assert lineage["entity"]["id"] == "table-1"


def test_sample_values_require_authentication_and_explicit_reader_role():
    from unittest.mock import AsyncMock
    from teoria.metadata.models import TableSampleData

    service = FakeMetadataService()
    service.get_table_samples = AsyncMock(
        return_value=TableSampleData(
            reference=_entity("table-1", "table", "customers").reference,
            available=True,
            columns=["x"],
            rows=[["[REDACTED]"]],
        )
    )
    settings = Settings(
        admin_auth_mode="bearer",
        admin_api_token="test-secret",
        admin_api_roles="metadata_admin",
    )
    client = TestClient(
        create_admin_app(
            settings=settings,
            catalog=RegistryLoader(REGISTRIES).load(),
            metadata_service=service,
        )
    )
    path = "/v1/admin/metadata/tables/table-1/sample-data"
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer test-secret"}
    assert client.get(path + "?include_values=true", headers=headers).status_code == 403
    service.get_table_samples.assert_not_called()
    result = client.get(path, headers=headers)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    service.get_table_samples.assert_awaited_once_with(
        "table-1", limit=10, include_values=False
    )
    settings.admin_api_roles = "metadata_sample_reader"
    privileged = TestClient(
        create_admin_app(
            settings=settings,
            catalog=RegistryLoader(REGISTRIES).load(),
            metadata_service=service,
        )
    )
    assert (
        privileged.get(path + "?include_values=true", headers=headers).status_code
        == 200
    )
    assert privileged.get(path + "?limit=51", headers=headers).status_code == 422


def test_profile_permission_error_is_403_not_missing_data():
    from unittest.mock import AsyncMock
    from teoria.metadata.openmetadata import OpenMetadataError

    service = FakeMetadataService()
    service.get_table_profile = AsyncMock(
        side_effect=OpenMetadataError(
            "openmetadata_api_error", "denied", status_code=403
        )
    )
    client = TestClient(
        create_admin_app(
            settings=Settings(),
            catalog=RegistryLoader(REGISTRIES).load(),
            metadata_service=service,
        )
    )
    result = client.get("/v1/admin/metadata/tables/table-1/profile")
    assert result.status_code == 403


def test_public_metadata_read_does_not_disable_write_or_sample_authentication():
    settings = Settings(
        admin_auth_mode="bearer",
        admin_api_token="test-secret",
        admin_metadata_public_read=True,
    )
    client = TestClient(
        create_admin_app(
            settings=settings,
            catalog=RegistryLoader(REGISTRIES).load(),
            metadata_service=FakeMetadataService(),
        )
    )
    for path in [
        "status",
        "services",
        "databases",
        "schemas",
        "tables",
        "tables/teoria.teoria_data.public_procurement.contracts",
        "tables/table-1/lineage",
    ]:
        assert client.get("/v1/admin/metadata/" + path).status_code == 200
    assert (
        client.get(
            "/v1/admin/metadata/status",
            headers={"Authorization": "Bearer obsolete-token"},
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/admin/metadata/tables/table-1/sample-data").status_code == 401
    )
    assert client.post("/v1/admin/bindings", json={}).status_code == 401
    assert (
        client.post("/v1/admin/intelligence/binding-suggestions", json={}).status_code
        == 401
    )


def test_metadata_read_requires_authentication_by_default():
    settings = Settings(admin_auth_mode="bearer", admin_api_token="test-secret")
    client = TestClient(
        create_admin_app(
            settings=settings,
            catalog=RegistryLoader(REGISTRIES).load(),
            metadata_service=FakeMetadataService(),
        )
    )
    assert client.get("/v1/admin/metadata/status").status_code == 401
    assert client.get("/v1/admin/metadata/tables").status_code == 401


def test_admin_session_validates_token_and_returns_only_principal():
    settings = Settings(
        admin_auth_mode="bearer",
        admin_api_token="test-secret",
        admin_metadata_public_read=True,
        admin_api_actor="user:reviewer",
    )
    client = TestClient(
        create_admin_app(settings=settings, catalog=RegistryLoader(REGISTRIES).load())
    )
    path = "/v1/admin/auth/session"
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": "Bearer wrong-token"}).status_code
        == 401
    )
    response = client.get(path, headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200
    assert response.json()["actor"] == "user:reviewer"
    assert "metadata_admin" in response.json()["roles"]
    assert "test-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_binding_context_filter_validates_and_forwards_exact_ids():
    from unittest.mock import AsyncMock, Mock

    repository = Mock(list_bindings=AsyncMock())
    repository.list_bindings.return_value = []
    client = TestClient(
        create_admin_app(
            settings=Settings(),
            catalog=RegistryLoader(REGISTRIES).load(),
            binding_repository=repository,
        )
    )
    binding_id = "00000000-0000-0000-0000-000000000001"
    assert client.get("/v1/admin/bindings?binding_id=" + binding_id).status_code == 200
    from uuid import UUID

    repository.list_bindings.assert_called_once_with(
        status=None, limit=100, binding_ids=[UUID(binding_id)]
    )
    assert client.get("/v1/admin/bindings?binding_id=invalid").status_code == 422
