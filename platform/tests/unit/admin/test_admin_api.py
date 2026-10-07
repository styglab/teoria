from pathlib import Path

from fastapi.testclient import TestClient

from teoria.admin.api import create_admin_app
from teoria.config import Settings
from teoria.registry.loader import RegistryLoader


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_admin_api_exposes_overview_and_runtime_contract_graph() -> None:
    app = create_admin_app(settings=Settings(), catalog=RegistryLoader(REGISTRIES).load())
    client = TestClient(app)

    overview = client.get("/v1/admin/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["runtime_contract_domains"] == 3
    assert overview.json()["counts"]["runtime_object_types"] == 44
    assert overview.json()["counts"]["eligibility_rules"] == 12
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
    assessment = next(item for item in capabilities if item["id"] == "assess_company_bid_eligibility")
    assert assessment["kind"] == "decision"
    assert assessment["exposure"] == "public"
    assert next(
        item for item in capabilities if item["id"] == "get_bid_notices_by_ids"
    )["exposure"] == "internal"
    assert assessment["steps"] == []
    rules = client.get("/v1/admin/eligibility-rules").json()["eligibility_rules"]
    direct_production = next(item for item in rules if item["id"] == "holds_valid_direct_production_confirmation")
    assert direct_production["evaluator"] == "product_certificate_valid"
    assert "public_procurement.direct_production_confirmation.detailed_product_code" in direct_production["required_facts"]
    assert any(source["type"] == "database" for source in client.get("/v1/admin/sources").json()["sources"])
    assert client.get("/v1/admin/mappings").json()["mappings"][0]["binding_count"] > 0
    assert any(link["kind"] == "mapping" for link in client.get("/v1/admin/lineage").json()["links"])

    contracts = client.get("/v1/admin/runtime-contracts")
    assert contracts.status_code == 200
    assert len(contracts.json()["runtime_contracts"]) == 3

    graph = client.get("/v1/admin/runtime-contracts/public_procurement/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["runtime_contract"]["id"] == "public_procurement"
    assert any(node["id"] == "public_procurement.contract" for node in payload["nodes"])
    assert any(node["id"] == "company.business_registration" and node["external"] for node in payload["nodes"])
    assert any(edge["link_type"] == "contract_participation_is_for_contract" for edge in payload["edges"])
    link = next(edge for edge in payload["edges"] if edge["link_type"] == "contract_participation_is_for_contract")
    assert link["ontology"] == "public_procurement"
    assert link["name"]

    combined = client.get("/v1/admin/runtime-contracts/all/graph").json()
    assert combined["runtime_contract"]["id"] == "all"
    assert any(node["id"] == "company.business_registration" and not node["external"] for node in combined["nodes"])
    assert any(edge["source"] == "company.business_registration" for edge in combined["edges"])


def test_admin_api_removes_legacy_ontology_routes() -> None:
    app = create_admin_app(settings=Settings(), catalog=RegistryLoader(REGISTRIES).load())
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

    assert client.post("/v1/admin/intelligence/suggestions", json=payload).status_code == 401
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

    forbidden = TestClient(create_admin_app(
        settings=Settings(
            admin_auth_mode="bearer", admin_api_token="test-secret",
            admin_api_roles="metadata_reviewer",
        ),
        catalog=RegistryLoader(REGISTRIES).load(),
    )).post(
        "/v1/admin/ontology-authoring/ontologies/procurement/versions",
        json={"version": "0.3.0"}, headers={"Authorization": "Bearer test-secret"},
    )
    assert forbidden.status_code == 403


def test_admin_api_exposes_pipeline_bid_check_results() -> None:
    class Reader:
        def list_notices(self, *, page: int, page_size: int, query: str | None,
                         bid_status: str | None, work_type: str | None,
                         extraction_status: str | None, review_status: str | None):
            assert (page, page_size, query) == (2, 20, "테스트")
            assert (bid_status, work_type, extraction_status, review_status) == (
                "open", "service", "extracted", "required"
            )
            return {"items": [{"bid_notice_id": "R26TEST:000", "requirement_count": 2}], "page": 2, "page_size": 20, "total": 21, "total_pages": 2}

        def get_requirements(self, bid_notice_id: str):
            assert bid_notice_id == "R26TEST:000"
            return [{"requirement_id": "requirement-1", "original_text": "중소기업이어야 한다"}]

    app = create_admin_app(
        settings=Settings(), catalog=RegistryLoader(REGISTRIES).load(), bid_check_reader=Reader()
    )
    client = TestClient(app)

    page = client.get(
        "/v1/admin/bid-check/notices?page=2&page_size=20&query=테스트"
        "&bid_status=open&work_type=service&extraction_status=extracted&review_status=required"
    ).json()
    assert page["items"][0]["requirement_count"] == 2
    assert page["total_pages"] == 2
    requirements = client.get(
        "/v1/admin/bid-check/notices/R26TEST%3A000/requirements"
    ).json()["requirements"]
    assert requirements[0]["requirement_id"] == "requirement-1"
