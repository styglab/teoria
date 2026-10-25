from unittest.mock import AsyncMock

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.metadata_management.catalog.admin_api import create_metadata_router
from teoria.features.metadata_management.catalog.asset_context import AssetContextService, asset_targets
from teoria.settings import Settings

TABLE_ID = "13d2a08b-9b29-4310-8d9a-a5d6bdf53f7c"
DOCUMENT = {
    "id": TABLE_ID,
    "name": "contracts",
    "fullyQualifiedName": "svc.db.schema.contracts",
    "service": {"name": "svc"},
    "database": {"name": "db"},
    "databaseSchema": {"name": "schema"},
    "columns": [
        {
            "name": "amount",
            "fullyQualifiedName": "svc.db.schema.contracts.amount",
            "tags": [{"source": "Glossary", "tagFQN": "Procurement.Amount"}],
            "children": [
                {
                    "name": "nested",
                    "fullyQualifiedName": "svc.db.schema.contracts.amount.nested",
                }
            ],
        }
    ],
}


def client(service, auth=False):
    app = FastAPI()
    settings = Settings(
        admin_auth_mode="bearer" if auth else "disabled",
        admin_api_token="synthetic-test-token",
    )
    app.include_router(create_metadata_router(None, AdminAuthorizer(settings), service))
    return TestClient(app)


def test_context_combines_sources_and_auth_without_writes():
    calls = []

    async def operations(*args):
        calls.append(args)
        return [{"pipeline_id": "explicit", "status": "completed"}]

    async def application(table_id, assets, terms):
        assert table_id == TABLE_ID
        assert assets == [
            "svc.db.schema.contracts",
            "svc.db.schema.contracts.amount",
            "svc.db.schema.contracts.amount.nested",
        ]
        assert terms == ["Procurement.Amount"]
        return {"bindings": [], "suggestions": []}

    om = type("Client", (), {"get": AsyncMock(return_value=DOCUMENT)})()
    service = AssetContextService(
        om,
        database_service="svc",
        operations_reader=operations,
        application_reader=application,
    )
    http = client(service, True)
    path = "/v1/admin/metadata/asset-context/" + TABLE_ID
    assert http.get(path).status_code == 401
    result = http.get(path, headers={"Authorization": "Bearer synthetic-test-token"})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json()["operations"]["data"][0]["pipeline_id"] == "explicit"
    assert result.json()["business"]["glossary_terms"] == ["Procurement.Amount"]
    assert calls == [("db", "schema", "contracts")]
    assert (
        http.get(
            "/v1/admin/metadata/asset-context/not-a-uuid",
            headers={"Authorization": "Bearer synthetic-test-token"},
        ).status_code
        == 422
    )


def test_unavailable_operations_keep_business_and_technical_visible():
    async def unavailable(*args):
        raise psycopg.OperationalError("sensitive connection information")

    om = type("Client", (), {"get": AsyncMock(return_value=DOCUMENT)})()
    service = AssetContextService(
        om,
        database_service="svc",
        operations_reader=unavailable,
        application_reader=AsyncMock(return_value={"bindings": [], "suggestions": []}),
    )
    result = client(service).get("/v1/admin/metadata/asset-context/" + TABLE_ID)
    assert result.status_code == 200
    assert result.json()["operations"]["status"] == "unavailable"
    assert result.json()["business"]["status"] == "available"
    assert result.json()["technical"]["name"] == "contracts"
    assert "sensitive" not in result.text


def test_does_not_attach_pipeline_by_name_across_services():
    async def must_not_run(*args):
        raise AssertionError("Wrong data service")

    om = type("Client", (), {"get": AsyncMock(return_value=DOCUMENT)})()
    service = AssetContextService(
        om, database_service="another_service", operations_reader=must_not_run
    )
    result = client(service).get("/v1/admin/metadata/asset-context/" + TABLE_ID)
    assert result.json()["operations"]["status"] == "not_linked"
    assert result.json()["business"]["status"] == "unconfigured"


def test_only_authoritative_column_fqns_and_glossary_tags_are_targets():
    assets, terms = asset_targets(
        {
            **DOCUMENT,
            "tags": [{"tagFQN": "PersonalData.Name", "source": "Classification"}],
            "columns": [
                {"name": "unknown"},
                {
                    "name": "neighbor",
                    "fullyQualifiedName": "svc.db.schema.contracts.neighbor",
                },
            ],
        }
    )
    assert "svc.db.schema.contracts.unknown" not in assets
    assert terms == []


def test_public_context_read_is_available_without_admin_token():
    service = type(
        "Context",
        (),
        {"get": AsyncMock(return_value={"technical": {"name": "contracts"}})},
    )()
    app = FastAPI()
    app.include_router(
        create_metadata_router(
            None,
            AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer", admin_api_token="synthetic-test-token"
                )
            ),
            service,
            public_read=True,
        )
    )
    result = TestClient(app).get("/v1/admin/metadata/asset-context/" + TABLE_ID)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    service.get.assert_awaited_once_with(TABLE_ID)
