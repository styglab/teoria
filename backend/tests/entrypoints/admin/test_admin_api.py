from pathlib import Path

from fastapi.testclient import TestClient

from teoria.entrypoints.admin_api import create_admin_app
from teoria.settings import Settings
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


REGISTRIES = Path("archive/procurement_services/platform/registries")


def test_admin_api_exposes_overview_and_runtime_contract_graph() -> None:
    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load()
    )
    client = TestClient(app)

    overview = client.get("/v1/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["runtime_contract_domains"] == 2
    assert overview.json()["counts"]["runtime_contracts"] == 2
    assert overview.json()["counts"]["business_domains"] == 2
    assert overview.json()["counts"]["runtime_object_types"] == 38
    assert overview.json()["validation"]["status"] == "valid"

    release = client.get("/v1/admin/registry-release")
    assert release.status_code == 200
    assert release.json() == {
        "version": None,
        "git_commit": None,
        "checksum": None,
        "published_at": None,
        "status": "draft",
    }

    validation = client.get("/v1/admin/validation")
    assert validation.status_code == 200
    assert validation.json() == {
        "status": "valid",
        "diagnostic_count": 0,
        "diagnostics": [],
    }

    capabilities = client.get("/v1/admin/capabilities").json()["capabilities"]
    assert any(item["kind"] == "query" and item["steps"] for item in capabilities)
    assert (
        next(item for item in capabilities if item["id"] == "get_bid_notices_by_ids")[
            "exposure"
        ]
        == "internal"
    )
    assert any(
        source["type"] == "database"
        for source in client.get("/v1/admin/sources").json()["sources"]
    )
    assert client.get("/v1/admin/mappings").json()["mappings"][0]["binding_count"] > 0
    assert any(
        link["kind"] == "mapping"
        for link in client.get("/v1/admin/lineage").json()["links"]
    )

    contracts = client.get("/v1/admin/runtime-contracts")
    assert contracts.status_code == 200
    assert len(contracts.json()["runtime_contracts"]) == 2

    graph = client.get("/v1/admin/runtime-contracts/public_procurement/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["runtime_contract"]["id"] == "public_procurement"
    assert any(node["id"] == "public_procurement.contract" for node in payload["nodes"])
    assert any(
        node["id"] == "company.business_registration" and node["external"]
        for node in payload["nodes"]
    )
    assert any(
        edge["link_type"] == "contract_participation_is_for_contract"
        for edge in payload["edges"]
    )
    link = next(
        edge
        for edge in payload["edges"]
        if edge["link_type"] == "contract_participation_is_for_contract"
    )
    assert link["ontology"] == "public_procurement"
    assert link["name"]

    combined = client.get("/v1/admin/runtime-contracts/all/graph").json()
    assert combined["runtime_contract"]["id"] == "all"
    assert any(
        node["id"] == "company.business_registration" and not node["external"]
        for node in combined["nodes"]
    )
    assert any(
        edge["source"] == "company.business_registration" for edge in combined["edges"]
    )


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
