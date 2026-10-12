from datetime import date

import pytest

from teoria.context.service import ContextEngine
from teoria.policy import PolicyDecision, PolicyDeniedError


class QueryHandler:
    def __init__(self):
        self.events = []

    def describe(self, question):
        return {
            "type": "semantic_query", "query_type": "example",
            "concept": "example.Record.value", "capability_id": "calculate",
        }

    async def plan(self, question, *, as_of, principal):
        self.events.append(("plan", principal))
        return {
            "query_type": "example", "question": question,
            "concept": {"stable_key": "example.Record.value"},
            "capability_id": "calculate", "inputs": {"value": 3},
            "as_of": as_of.isoformat(),
        }

    async def execute(self, plan, principal, decision):
        self.events.append(("execute", principal))
        return {"value": plan["inputs"]["value"], "decision_id": decision.decision_id}


class CapturingPolicy:
    def __init__(self, deny_action=None):
        self.requests = []
        self.deny_action = deny_action

    async def decide(self, **request):
        self.requests.append(request)
        return PolicyDecision(
            allow=request["action"] != self.deny_action,
            reason="test_policy", decision_id=request["action"],
        )


@pytest.mark.asyncio
async def test_injected_query_handler_keeps_both_policy_checks_and_principal():
    handler = QueryHandler()
    policy = CapturingPolicy()
    engine = ContextEngine(object(), None, object(), query_handler=handler, policy_evaluator=policy)
    result = await engine.query("example question", as_of=date(2026, 10, 12), actor="user:test", roles=frozenset({"reader"}))
    assert result == {"value": 3, "decision_id": "context.execute"}
    assert [request["action"] for request in policy.requests] == ["context.plan", "context.execute"]
    assert [event[0] for event in handler.events] == ["plan", "execute"]
    assert all(event[1].actor == "user:test" and event[1].roles == frozenset({"reader"}) for event in handler.events)
    assert policy.requests[1]["resource"]["concept"] == "example.Record.value"
    assert policy.requests[1]["context"]["inputs"] == {"value": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("deny_action,events", [("context.plan", []), ("context.execute", ["plan"])])
async def test_injected_handler_cannot_skip_policy_denial(deny_action, events):
    handler = QueryHandler()
    policy = CapturingPolicy(deny_action)
    engine = ContextEngine(object(), None, object(), query_handler=handler, policy_evaluator=policy)
    with pytest.raises(PolicyDeniedError):
        await engine.query("example question")
    assert [event[0] for event in handler.events] == events
