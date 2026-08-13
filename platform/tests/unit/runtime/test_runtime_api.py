from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teoria.config import Settings
from teoria.registry.loader import RegistryLoader
from teoria.runtime.api import create_runtime_app
from teoria.runtime.capability.runner import CapabilityResult


REGISTRIES = Path(__file__).parents[3] / "registries"


class CapturingRunner:
    def __init__(self) -> None:
        self.call = None

    async def run(self, catalog, capability_id, inputs):
        self.call = capability_id, inputs
        return CapabilityResult(capability_id=capability_id)


def test_runtime_api_requires_bearer_auth_and_executes_capability() -> None:
    runner = CapturingRunner()
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=runner,
    )
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/capabilities").status_code == 401

    headers = {"Authorization": "Bearer test-token"}
    capabilities = client.get("/v1/capabilities", headers=headers)
    assert capabilities.status_code == 200
    assert any(item["id"] == "search_public_procurement_contracts" for item in capabilities.json()["capabilities"])
    assessment = next(
        item for item in capabilities.json()["capabilities"]
        if item["id"] == "assess_company_bid_eligibility"
    )
    assert assessment["kind"] == "compute"
    assert "assessment.requirement_assessment" in assessment["effects"]["produces"]
    assert client.get("/v1/version", headers=headers).json()["registry"]["version"] == "2026.08.13.2"

    response = client.post(
        "/v1/capabilities/search_public_procurement_contracts:execute",
        headers=headers,
        json={"inputs": {"concluded_date_from": "2026-01-01", "concluded_date_to": "2026-01-02"}},
    )
    assert response.status_code == 200
    assert response.json()["capability"] == "search_public_procurement_contracts"
    assert response.json()["registry"]["version"] == "2026.08.13.2"
    assert runner.call[0] == "search_public_procurement_contracts"
    assert runner.call[1]["concluded_date_from"].isoformat() == "2026-01-01"


def test_runtime_api_rejects_invalid_capability_input() -> None:
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=CapturingRunner(),
    )
    response = TestClient(app).post(
        "/v1/capabilities/search_public_procurement_contracts:execute",
        headers={"Authorization": "Bearer test-token"},
        json={"inputs": {}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_capability_input"


def test_bid_notice_search_discovery_exposes_pagination_and_sort_contract() -> None:
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=CapturingRunner(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    capabilities = client.get("/v1/capabilities", headers=headers).json()["capabilities"]
    search = next(item for item in capabilities if item["id"] == "search_bid_notices")
    properties = search["input_schema"]["properties"]

    assert properties["sort"]["enum"] == ["published_desc", "deadline_asc"]
    assert properties["sort"]["default"] == "published_desc"
    assert properties["page"] == {"type": "integer", "default": 1, "minimum": 1}
    assert properties["page_size"]["maximum"] == 100

    invalid = client.post(
        "/v1/capabilities/search_bid_notices:execute",
        headers=headers,
        json={"inputs": {
            "notice_published_at_from": "2026-08-01T00:00:00Z",
            "notice_published_at_to": "2026-08-31T00:00:00Z",
            "page": 0,
        }},
    )
    assert invalid.status_code == 422


def test_contract_capabilities_expose_root_contract_pagination() -> None:
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=CapturingRunner(),
    )
    capabilities = TestClient(app).get(
        "/v1/capabilities",
        headers={"Authorization": "Bearer test-token"},
    ).json()["capabilities"]

    contract_search = next(
        item for item in capabilities if item["id"] == "search_public_procurement_contracts"
    )["input_schema"]["properties"]
    company_history = next(
        item for item in capabilities
        if item["id"] == "get_company_public_procurement_contracts"
    )["input_schema"]["properties"]

    assert contract_search["sort"]["enum"] == ["concluded_desc", "amount_desc"]
    assert contract_search["page_size"]["maximum"] == 100
    assert company_history["sort"]["enum"] == ["contract_desc"]
    assert company_history["page"]["default"] == 1


def test_runtime_api_can_require_a_published_registry() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    catalog.release = None

    with pytest.raises(RuntimeError, match="published, checksum-valid Registry"):
        create_runtime_app(
            settings=Settings(runtime_api_token="test-token", registry_require_published=True),
            catalog=catalog,
            runner=CapturingRunner(),
        )
