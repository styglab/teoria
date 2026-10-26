from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, Field
from teoria.features.access_control.policy import PolicyPrincipal
from teoria.features.runtime.dependencies import (
    RuntimeServicesDependency,
    authorize,
    require_policy,
)
from teoria.features.runtime.capability.presentation import serialize_capability_result
from teoria.features.runtime.capability.runner import CapabilityExecutionError
from teoria.features.runtime.capability.schema import (
    capability_input_schema,
    coerce_capability_inputs,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ExecutionOptions(BaseModel):
    max_objects: int = Field(default=200, ge=1, le=1000)
    include_property_provenance: bool = False


class CapabilityExecutionRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    options: ExecutionOptions = Field(default_factory=ExecutionOptions)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/version")
async def version(
    services: RuntimeServicesDependency, principal: PolicyPrincipal = Depends(authorize)
) -> dict[str, Any]:
    await require_policy(
        services=services,
        principal=principal,
        action="runtime.version.read",
        resource={"type": "runtime"},
    )
    return {
        "runtime_api": "1",
        "registry": services.catalog.release.public_dict()
        if services.catalog.release
        else {"status": "draft"},
        "runtime_artifact": services.bundle.provenance() if services.bundle else None,
    }


@router.get("/v1/capabilities")
async def list_capabilities(
    services: RuntimeServicesDependency,
    principal: PolicyPrincipal = Depends(authorize),
) -> dict[str, list[dict[str, Any]]]:
    await require_policy(
        services=services,
        principal=principal,
        action="capability.discover",
        resource={"type": "capability_collection", "exposure": "public"},
    )
    return {
        "capabilities": [
            {
                "id": capability.id,
                "version": capability.version,
                "definition_checksum": services.catalog.capability_checksums[
                    (capability.id, capability.version)
                ],
                "name": capability.name,
                "description": capability.description,
                "kind": capability.kind,
                "exposure": capability.exposure,
                "processor": capability.processor,
                "effects": capability.effects.model_dump(),
                "returns": capability.returns,
                "input_schema": capability_input_schema(services.catalog, capability),
            }
            for capability in services.catalog.capabilities.values()
            if capability.lifecycle.status == "active"
            and capability.exposure == "public"
        ]
    }


@router.post("/v1/capabilities/{capability_id}:execute")
async def execute_capability(
    capability_id: str,
    request: CapabilityExecutionRequest,
    services: RuntimeServicesDependency,
    principal: PolicyPrincipal = Depends(authorize),
) -> dict[str, Any]:
    execution_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    capability = services.catalog.capabilities.get(capability_id)
    if capability is None or capability.exposure != "public":
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_capability", "message": capability_id},
        )
    if capability.lifecycle.status == "deprecated":
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_capability",
                "message": capability_id,
                "replacement_ids": capability.lifecycle.replacement_ids,
                "sunset_at": capability.lifecycle.sunset_at,
            },
        )
    policy_decision = await require_policy(
        services=services,
        principal=principal,
        action="capability.execute",
        resource={
            "type": "capability",
            "id": capability.id,
            "kind": capability.kind,
            "exposure": capability.exposure,
            "required_permissions": capability.policy.permissions,
            "effects": capability.effects.model_dump(mode="json"),
        },
        context={"inputs": request.inputs},
    )
    schema = capability_input_schema(services.catalog, capability)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            request.inputs
        ),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_capability_input", "message": errors[0].message},
        )
    inputs = coerce_capability_inputs(services.catalog, capability, request.inputs)
    try:
        result = await services.runner.run(services.catalog, capability_id, inputs)
    except CapabilityExecutionError as exc:
        status_code = {
            "capability_timeout": 504,
            "bid_notice_not_found": 404,
            "invalid_bid_notice_id": 422,
        }.get(exc.code, 502)
        raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
    response = serialize_capability_result(
        result,
        max_objects=request.options.max_objects,
        include_property_provenance=request.options.include_property_provenance,
    )
    response["registry"] = (
        services.catalog.release.public_dict()
        if services.catalog.release
        else {"status": "draft"}
    )
    response["runtime_artifact"] = (
        services.bundle.provenance() if services.bundle else None
    )
    response["capability_version"] = {
        "id": capability.id,
        "version": capability.version,
        "definition_checksum": services.catalog.capability_checksums[
            (capability.id, capability.version)
        ],
    }
    response["execution"] = {
        "execution_id": execution_id,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "capability_id": capability.id,
        "capability_version": capability.version,
        "capability_checksum": services.catalog.capability_checksums[
            (capability.id, capability.version)
        ],
        "artifact_version": services.bundle.version if services.bundle else None,
        "artifact_checksum": services.bundle.bundle_checksum
        if services.bundle
        else None,
        "authorization": policy_decision.model_dump(mode="json"),
    }
    logger.info(
        "runtime capability executed",
        extra={
            "capability_id": capability_id,
            "registry_version": (
                services.catalog.release.version if services.catalog.release else None
            ),
            "runtime_bundle_version": services.bundle.version
            if services.bundle
            else None,
            "runtime_bundle_checksum": (
                services.bundle.bundle_checksum if services.bundle else None
            ),
        },
    )
    return response
