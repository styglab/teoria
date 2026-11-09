"""Runtime HTTP service bundle, authorization and request dependencies."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request

from teoria.platform.access_control.policy import (
    PolicyEvaluationError,
    PolicyEvaluator,
    PolicyPrincipal,
)
from teoria.platform.ontology.contracts.artifact import RuntimeBundleManifest
from teoria.platform.ontology.contracts.loader import RegistryCatalog
from teoria.platform.ontology.runtime.capability.runner import CapabilityRunner
from teoria.settings import Settings


@dataclass
class RuntimeServices:
    settings: Settings
    catalog: RegistryCatalog
    runner: CapabilityRunner
    policy_evaluator: PolicyEvaluator
    bundle: RuntimeBundleManifest | None = None
    resources: list[Any] = field(default_factory=list)
    owned_cache: Any | None = None


def get_runtime_services(request: Request) -> RuntimeServices:
    return request.app.state.runtime_services


RuntimeServicesDependency = Annotated[RuntimeServices, Depends(get_runtime_services)]


def authorize(
    services: RuntimeServicesDependency,
    authorization: str | None = Header(default=None),
    actor: str | None = Header(default=None, alias="X-Teoria-Actor"),
    roles: str | None = Header(default=None, alias="X-Teoria-Roles"),
    service: str | None = Header(default=None, alias="X-Teoria-Service"),
) -> PolicyPrincipal:
    expected = f"Bearer {services.settings.runtime_api_token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "invalid bearer token"},
        )
    return PolicyPrincipal(
        actor=actor or "service:runtime-client",
        roles=frozenset(
            item.strip() for item in (roles or "").split(",") if item.strip()
        ),
        service=service or "runtime-client",
    )


async def require_policy(
    *,
    services: RuntimeServices,
    principal: PolicyPrincipal,
    action: str,
    resource: dict[str, Any],
    context: dict[str, Any] | None = None,
):
    try:
        decision = await services.policy_evaluator.decide(
            principal=principal,
            action=action,
            resource=resource,
            context=context,
        )
    except PolicyEvaluationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "policy_unavailable", "message": str(exc)},
        ) from exc
    if not decision.allow:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "policy_denied",
                "reason": decision.reason,
                "decision_id": decision.decision_id,
            },
        )
    return decision
