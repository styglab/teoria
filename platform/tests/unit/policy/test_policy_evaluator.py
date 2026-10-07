import httpx
import pytest

from teoria.config import Settings
from teoria.policy import (
    DisabledPolicyEvaluator,
    OpaPolicyEvaluator,
    PolicyEvaluationError,
    PolicyPrincipal,
    create_policy_evaluator,
)


@pytest.mark.asyncio
async def test_opa_policy_evaluator_sends_stable_input_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/teoria/authz/decision"
        payload = __import__("json").loads(request.content)
        assert payload["input"] == {
            "principal": {
                "actor": "user:test",
                "roles": ["procurement_reader"],
                "service": "admin-api",
                "authenticated": True,
            },
            "action": "capability.execute",
            "resource": {
                "type": "capability",
                "id": "search_bid_notices",
                "required_permissions": [],
            },
            "context": {"query_type": "bid_notice_search"},
        }
        return httpx.Response(200, json={
            "decision_id": "decision-1",
            "result": {
                "allow": True,
                "reason": "public_capability",
                "metadata": {"policy_revision": "test"},
            }
        })

    evaluator = OpaPolicyEvaluator(
        "http://opa:8181",
        transport=httpx.MockTransport(handler),
    )
    decision = await evaluator.decide(
        principal=PolicyPrincipal(
            actor="user:test",
            roles=frozenset({"procurement_reader"}),
            service="admin-api",
        ),
        action="capability.execute",
        resource={
            "type": "capability",
            "id": "search_bid_notices",
            "required_permissions": [],
        },
        context={"query_type": "bid_notice_search"},
    )

    assert decision.allow is True
    assert decision.decision_id == "decision-1"
    assert decision.metadata["policy_revision"] == "test"


@pytest.mark.asyncio
async def test_opa_policy_evaluator_fails_closed_when_decision_is_undefined() -> None:
    evaluator = OpaPolicyEvaluator(
        "http://opa:8181",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})
        ),
    )

    with pytest.raises(PolicyEvaluationError, match="undefined"):
        await evaluator.decide(
            principal=PolicyPrincipal(actor="user:test"),
            action="context.execute",
            resource={"type": "semantic_query"},
        )


def test_production_requires_opa_policy_mode() -> None:
    with pytest.raises(RuntimeError, match="POLICY_MODE=opa"):
        create_policy_evaluator(Settings(environment="production"))


def test_development_uses_explicit_disabled_policy_adapter() -> None:
    assert isinstance(
        create_policy_evaluator(Settings(environment="development")),
        DisabledPolicyEvaluator,
    )
