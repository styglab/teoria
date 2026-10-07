from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.admin.auth import AdminAuthorizer
from teoria.admin.context_api import create_context_router
from teoria.config import Settings
from teoria.policy import PolicyDecision, PolicyDeniedError


class ContextEngineStub:
    async def plan(self, question, *, as_of, actor, roles):
        return {
            "operation": "plan",
            "question": question,
            "actor": actor,
            "roles": sorted(roles),
        }

    async def query(self, question, *, as_of, actor, roles):
        return {
            "operation": "execute",
            "question": question,
            "actor": actor,
            "roles": sorted(roles),
        }


def _client(engine) -> TestClient:
    settings = Settings(
        admin_api_actor="user:test",
        admin_api_roles="context_reader",
    )
    app = FastAPI()
    app.include_router(create_context_router(engine, AdminAuthorizer(settings)))
    return TestClient(app)


def test_context_api_separates_plan_and_execute_and_keeps_query_alias() -> None:
    client = _client(ContextEngineStub())

    planned = client.post("/v1/admin/context/plan", json={"question": "질문"})
    executed = client.post("/v1/admin/context/execute", json={"question": "질문"})
    legacy = client.post("/v1/admin/context/query", json={"question": "질문"})

    assert planned.json()["operation"] == "plan"
    assert executed.json()["operation"] == "execute"
    assert legacy.json()["operation"] == "execute"
    assert planned.json()["actor"] == "user:test"
    assert planned.json()["roles"] == ["context_reader"]


def test_context_api_returns_policy_denial_as_forbidden() -> None:
    class DeniedContextEngine(ContextEngineStub):
        async def plan(self, question, *, as_of, actor, roles):
            raise PolicyDeniedError(PolicyDecision(
                allow=False,
                reason="missing_context_permission",
                decision_id="deny-1",
            ))

    response = _client(DeniedContextEngine()).post(
        "/v1/admin/context/plan", json={"question": "질문"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "policy_denied",
        "reason": "missing_context_permission",
        "decision_id": "deny-1",
    }
