from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

import httpx
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from teoria.config import Settings


@dataclass(frozen=True)
class PolicyPrincipal:
    actor: str
    roles: frozenset[str] = frozenset()
    service: str | None = None
    authenticated: bool = True

    def as_input(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "roles": sorted(self.roles),
            "service": self.service,
            "authenticated": self.authenticated,
        }


class PolicyDecision(BaseModel):
    allow: bool
    reason: str
    decision_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyEvaluationError(RuntimeError):
    """Raised when a configured policy decision point cannot decide."""


class PolicyDeniedError(RuntimeError):
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


class PolicyEvaluator(Protocol):
    async def decide(
        self,
        *,
        principal: PolicyPrincipal,
        action: str,
        resource: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision: ...


class DisabledPolicyEvaluator:
    """Explicit development-only policy adapter."""

    async def decide(
        self,
        *,
        principal: PolicyPrincipal,
        action: str,
        resource: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            allow=True,
            reason="policy_disabled",
            metadata={"mode": "disabled"},
        )


class OpaPolicyEvaluator:
    def __init__(
        self,
        base_url: str,
        *,
        decision_path: str = "teoria/authz/decision",
        timeout_seconds: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.decision_path = decision_path.strip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def decide(
        self,
        *,
        principal: PolicyPrincipal,
        action: str,
        resource: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        payload = {
            "input": {
                "principal": principal.as_input(),
                "action": action,
                "resource": resource,
                "context": context or {},
            }
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/data/{self.decision_path}",
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PolicyEvaluationError("OPA policy evaluation failed") from exc

        if "result" not in body:
            raise PolicyEvaluationError("OPA decision was undefined")
        result = body["result"]
        if isinstance(result, bool):
            return PolicyDecision(
                allow=result,
                reason="opa_allow" if result else "opa_deny",
                decision_id=body.get("decision_id"),
            )
        if not isinstance(result, dict) or not isinstance(result.get("allow"), bool):
            raise PolicyEvaluationError("OPA decision must be a boolean or an object with allow")
        decision = PolicyDecision.model_validate(result)
        if decision.decision_id is None and body.get("decision_id") is not None:
            decision.decision_id = str(body["decision_id"])
        return decision


def create_policy_evaluator(settings: Settings) -> PolicyEvaluator:
    if settings.policy_mode == "disabled":
        if settings.environment == "production":
            raise RuntimeError("TEORIA_POLICY_MODE=opa is required in production")
        return DisabledPolicyEvaluator()
    return OpaPolicyEvaluator(
        settings.opa_url,
        decision_path=settings.opa_decision_path,
        timeout_seconds=settings.opa_timeout_seconds,
    )
