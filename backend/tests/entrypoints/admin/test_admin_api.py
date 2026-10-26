from pathlib import Path

from fastapi.testclient import TestClient

from teoria.entrypoints.admin_api import create_admin_app
from teoria.settings import Settings
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


REGISTRIES = Path("backend/tests/fixtures/registry")


def test_admin_api_exposes_overview_and_runtime_contract_graph() -> None:
    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load()
    )
    client = TestClient(app)

    overview = client.get("/v1/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["runtime_contracts"] == 1
    assert overview.json()["counts"]["runtime_object_types"] == 2
    assert overview.json()["validation"]["status"] == "valid"
    assert client.get("/v1/admin/registry-release").json()["status"] == "draft"
    assert client.get("/v1/admin/validation").json()["diagnostic_count"] == 0
    capabilities = client.get("/v1/admin/capabilities").json()["capabilities"]
    assert next(c for c in capabilities if c["id"] == "get_record")["exposure"] == "internal"
    assert client.get("/v1/admin/mappings").json()["mappings"][0]["binding_count"] > 0
    graph = client.get("/v1/admin/runtime-contracts/example/graph")
    assert graph.status_code == 200
    assert any(n["id"] == "example.record" for n in graph.json()["nodes"])
    assert any(e["link_type"] == "belongs_to" for e in graph.json()["edges"])
    assert client.get("/v1/admin/runtime-contracts/all/graph").status_code == 200


def test_admin_api_removes_legacy_ontology_routes() -> None:
    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load()
    )
    client = TestClient(app)
    assert client.get("/v1/admin/ontologies").status_code == 404
    assert client.get("/v1/admin/ontologies/all/graph").status_code == 404
    response = client.get("/v1/admin/runtime-contracts/unknown/graph")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "runtime_contract_not_found"


def test_admin_mutations_require_configured_bearer_token() -> None:
    app = create_admin_app(
        settings=Settings(
            admin_auth_mode="bearer",
            admin_api_token="test-secret",
            admin_api_actor="user:test-admin",
            admin_api_roles="metadata_admin",
        ),
        catalog=RegistryLoader(REGISTRIES).load(),
    )
    client = TestClient(app)
    payload = {
        "target_type": "openmetadata_table",
        "target_ref": "table-id",
        "suggestion_type": "description",
        "proposed_value": {"description": "설명"},
        "confidence": 0.9,
        "model_provider": "test",
        "model_name": "test",
        "policy_version": "1",
    }

    assert (
        client.post("/v1/admin/intelligence/suggestions", json=payload).status_code
        == 401
    )
    authenticated = client.post(
        "/v1/admin/intelligence/suggestions",
        json=payload,
        headers={"Authorization": "Bearer test-secret"},
    )
    assert authenticated.status_code == 503

    ontology_draft = client.post(
        "/v1/admin/ontology-authoring/ontologies/procurement/versions",
        json={"version": "0.3.0"},
    )
    assert ontology_draft.status_code == 401

    forbidden = TestClient(
        create_admin_app(
            settings=Settings(
                admin_auth_mode="bearer",
                admin_api_token="test-secret",
                admin_api_roles="metadata_reviewer",
            ),
            catalog=RegistryLoader(REGISTRIES).load(),
        )
    ).post(
        "/v1/admin/ontology-authoring/ontologies/procurement/versions",
        json={"version": "0.3.0"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert forbidden.status_code == 403
