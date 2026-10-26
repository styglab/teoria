from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teoria.settings import Settings
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.entrypoints.runtime_api import create_runtime_app
from teoria.features.runtime.capability.runner import CapabilityResult
from teoria.features.access_control.policy import PolicyDecision


REGISTRIES = Path("backend/tests/fixtures/registry")


def test_archived_document_capabilities_are_not_discoverable_or_executable() -> None:
    runner = CapturingRunner()
    client = TestClient(
        create_runtime_app(
            settings=Settings(runtime_api_token="test-token"),
            catalog=RegistryLoader(REGISTRIES).load(),
            runner=runner,
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    discovered = {
        item["id"]
        for item in client.get("/v1/capabilities", headers=headers).json()[
            "capabilities"
        ]
    }
    for identifier in (
        "get_bid_requirements",
        "get_bid_requirements_by_notice_ids",
        "get_bid_participation_findings",
        "assess_company_bid_eligibility",
        "assess_company_bid_eligibilities",
    ):
        assert identifier not in discovered
        assert (
            client.post(
                f"/v1/capabilities/{identifier}:execute",
                headers=headers,
                json={"inputs": {}},
            ).status_code
            == 404
        )
    assert runner.call is None


class CapturingRunner:
    def __init__(self) -> None:
        self.call = None

    async def run(self, catalog, capability_id, inputs):
        self.call = capability_id, inputs
        return CapabilityResult(capability_id=capability_id)


class DenyPolicy:
    async def decide(self, **request):
        return PolicyDecision(
            allow=False,
            reason="missing_capability_permission",
            decision_id="deny-1",
        )


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
    assert any(
        item["id"] == "search_records"
        for item in capabilities.json()["capabilities"]
    )
    assert client.get("/v1/version", headers=headers).json()["registry"] == {
        "status": "draft"
    }

    response = client.post(
        "/v1/capabilities/search_records:execute",
        headers=headers,
        json={
            "inputs": {
                "from_date": "2026-01-01",

            }
        },
    )
    assert response.status_code == 200
    assert response.json()["capability"] == "search_records"
    assert response.json()["registry"] == {"status": "draft"}
    assert (
        response.json()["capability_version"]["id"]
        == "search_records"
    )
    assert response.json()["capability_version"]["version"] == "1.0.0"
    assert response.json()["execution"]["execution_id"]
    assert response.json()["execution"]["capability_version"] == "1.0.0"
    assert runner.call[0] == "search_records"
    assert runner.call[1]["from_date"].isoformat() == "2026-01-01"


def test_runtime_api_rejects_invalid_capability_input() -> None:
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=CapturingRunner(),
    )
    response = TestClient(app).post(
        "/v1/capabilities/search_records:execute",
        headers={"Authorization": "Bearer test-token"},
        json={"inputs": {}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_capability_input"


def test_runtime_api_enforces_policy_before_capability_execution() -> None:
    runner = CapturingRunner()
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=runner,
        policy_evaluator=DenyPolicy(),
    )
    response = TestClient(app).post(
        "/v1/capabilities/search_records:execute",
        headers={"Authorization": "Bearer test-token"},
        json={
            "inputs": {
                "from_date": "2026-01-01",

            }
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "policy_denied",
        "reason": "missing_capability_permission",
        "decision_id": "deny-1",
    }
    assert runner.call is None


def test_runtime_api_does_not_discover_removed_capabilities() -> None:
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test-token"),
        catalog=RegistryLoader(REGISTRIES).load(),
        runner=CapturingRunner(),
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    discovered = {
        item["id"]
        for item in client.get(
            "/v1/capabilities",
            headers=headers,
        ).json()["capabilities"]
    }
    assert "analyze_bid_organization_field_companies" not in discovered
    assert "find_bid_relevant_companies" not in discovered
    assert "find_similar_bid_notices" not in discovered

    response = client.post(
        "/v1/capabilities/find_similar_bid_notices:execute",
        headers=headers,
        json={"inputs": {"bid_notice_id": "R26TEST:000"}},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "unknown_capability",
        "message": "find_similar_bid_notices",
    }












def test_runtime_api_can_require_a_published_registry() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    catalog.release = None

    with pytest.raises(RuntimeError, match="published, checksum-valid Registry"):
        create_runtime_app(
            settings=Settings(
                runtime_api_token="test-token", registry_require_published=True
            ),
            catalog=catalog,
            runner=CapturingRunner(),
        )


def test_production_runtime_requires_an_immutable_artifact() -> None:
    with pytest.raises(RuntimeError, match="RUNTIME_ARTIFACT"):
        create_runtime_app(
            settings=Settings(environment="production", runtime_api_token="test-token"),
            runner=CapturingRunner(),
        )
