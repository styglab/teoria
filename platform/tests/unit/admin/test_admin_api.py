from pathlib import Path

from fastapi.testclient import TestClient

from teoria.admin.api import create_admin_app
from teoria.config import Settings
from teoria.registry.loader import RegistryLoader


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_admin_api_exposes_overview_and_ontology_graph() -> None:
    app = create_admin_app(settings=Settings(), catalog=RegistryLoader(REGISTRIES).load())
    client = TestClient(app)

    overview = client.get("/v1/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["ontologies"] == 2
    assert overview.json()["validation"]["status"] == "valid"

    validation = client.get("/v1/admin/validation")
    assert validation.status_code == 200
    assert validation.json() == {
        "status": "valid",
        "diagnostic_count": 0,
        "diagnostics": [],
    }

    assert client.get("/v1/admin/capabilities").json()["capabilities"][0]["steps"]
    assert any(source["type"] == "database" for source in client.get("/v1/admin/sources").json()["sources"])
    assert client.get("/v1/admin/mappings").json()["mappings"][0]["binding_count"] > 0
    assert any(link["kind"] == "mapping" for link in client.get("/v1/admin/lineage").json()["links"])

    graph = client.get("/v1/admin/ontologies/public_procurement/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert any(node["id"] == "public_procurement.contract" for node in payload["nodes"])
    assert any(node["id"] == "company.business_registration" and node["external"] for node in payload["nodes"])
    assert any(edge["link_type"] == "contract_participation_is_for_contract" for edge in payload["edges"])
    link = next(edge for edge in payload["edges"] if edge["link_type"] == "contract_participation_is_for_contract")
    assert link["ontology"] == "public_procurement"
    assert link["name"]

    combined = client.get("/v1/admin/ontologies/all/graph").json()
    assert combined["ontology"]["id"] == "all"
    assert any(node["id"] == "company.business_registration" and not node["external"] for node in combined["nodes"])
    assert any(edge["source"] == "company.business_registration" for edge in combined["edges"])


def test_admin_api_returns_not_found_for_unknown_ontology() -> None:
    app = create_admin_app(settings=Settings(), catalog=RegistryLoader(REGISTRIES).load())
    response = TestClient(app).get("/v1/admin/ontologies/unknown/graph")
    assert response.status_code == 404
