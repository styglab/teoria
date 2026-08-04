from pathlib import Path

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

    response = client.post(
        "/v1/capabilities/search_public_procurement_contracts:execute",
        headers=headers,
        json={"inputs": {"concluded_date_from": "2026-01-01", "concluded_date_to": "2026-01-02"}},
    )
    assert response.status_code == 200
    assert response.json()["capability"] == "search_public_procurement_contracts"
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
