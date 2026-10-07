from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, Field

from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.secrets import EnvironmentSecretProvider
from teoria.config import Settings, bootstrap_settings
from teoria.registry.artifact import RuntimeBundleLoader, RegistryArtifactStore
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.runtime.capability.presentation import serialize_capability_result
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityRunner
from teoria.runtime.capability.schema import capability_input_schema, coerce_capability_inputs
from teoria.runtime.cache import create_runtime_cache


logger = logging.getLogger(__name__)


class ExecutionOptions(BaseModel):
    max_objects: int = Field(default=200, ge=1, le=1000)
    include_property_provenance: bool = False


class CapabilityExecutionRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    options: ExecutionOptions = Field(default_factory=ExecutionOptions)


def create_runtime_app(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    runner: CapabilityRunner | None = None,
) -> FastAPI:
    resolved_settings = settings or bootstrap_settings()
    if not resolved_settings.runtime_api_token:
        raise RuntimeError("TEORIA_RUNTIME_API_TOKEN is required")
    runtime_bundle = None
    if catalog is not None:
        resolved_catalog = catalog
    elif resolved_settings.runtime_artifact_path is not None:
        loaded_bundle = RuntimeBundleLoader(
            resolved_settings.runtime_artifact_path
        ).load()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
    elif resolved_settings.runtime_artifact_store is not None:
        loaded_bundle = RegistryArtifactStore(
            resolved_settings.runtime_artifact_store
        ).load_active()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
    elif resolved_settings.environment == "production":
        raise RuntimeError(
            "TEORIA_RUNTIME_ARTIFACT_PATH or TEORIA_RUNTIME_ARTIFACT_STORE "
            "is required in production"
        )
    else:
        resolved_catalog = RegistryLoader(resolved_settings.registry_path).load()
    if resolved_settings.registry_require_published and (
        resolved_catalog.release is None or resolved_catalog.release.status != "published"
    ):
        raise RuntimeError("a published, checksum-valid Registry release is required")
    resolved_runner = runner or CapabilityRunner(
        ProviderExecutor(
            timeout_seconds=resolved_settings.source_timeout_seconds,
            max_attempts=resolved_settings.source_max_attempts,
            secret_provider=EnvironmentSecretProvider(),
        ),
        timeout_seconds=resolved_settings.capability_timeout_seconds,
        max_pages=resolved_settings.source_max_pages,
        cache=create_runtime_cache(
            resolved_settings.runtime_cache_backend,
            url=resolved_settings.runtime_cache_url,
            prefix=resolved_settings.runtime_cache_prefix,
        ),
    )
    app = FastAPI(
        title="Teoria Runtime API",
        version="1.0.0",
        root_path=resolved_settings.runtime_api_root_path,
    )

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {resolved_settings.runtime_api_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "invalid bearer token"})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/version", dependencies=[Depends(authorize)])
    async def version() -> dict[str, Any]:
        return {
            "runtime_api": "1",
            "registry": resolved_catalog.release.public_dict() if resolved_catalog.release else {"status": "draft"},
            "runtime_artifact": runtime_bundle.provenance() if runtime_bundle else None,
        }

    @app.get("/v1/capabilities", dependencies=[Depends(authorize)])
    async def list_capabilities() -> dict[str, list[dict[str, Any]]]:
        return {
            "capabilities": [
                {
                    "id": capability.id,
                    "version": capability.version,
                    "definition_checksum": resolved_catalog.capability_checksums[
                        (capability.id, capability.version)
                    ],
                    "name": capability.name,
                    "description": capability.description,
                    "kind": capability.kind,
                    "exposure": capability.exposure,
                    "processor": capability.processor,
                    "effects": capability.effects.model_dump(),
                    "returns": capability.returns,
                    "input_schema": capability_input_schema(resolved_catalog, capability),
                }
                for capability in resolved_catalog.capabilities.values()
                if capability.lifecycle.status == "active"
                and capability.exposure == "public"
            ]
        }

    @app.post("/v1/capabilities/{capability_id}:execute", dependencies=[Depends(authorize)])
    async def execute_capability(
        capability_id: str,
        request: CapabilityExecutionRequest,
    ) -> dict[str, Any]:
        execution_id = str(uuid4())
        started_at = datetime.now(timezone.utc)
        capability = resolved_catalog.capabilities.get(capability_id)
        if capability is None or capability.exposure != "public":
            raise HTTPException(status_code=404, detail={"code": "unknown_capability", "message": capability_id})
        if capability.lifecycle.status == "deprecated":
            raise HTTPException(status_code=410, detail={
                "code": "deprecated_capability",
                "message": capability_id,
                "replacement_ids": capability.lifecycle.replacement_ids,
                "sunset_at": capability.lifecycle.sunset_at,
            })
        schema = capability_input_schema(resolved_catalog, capability)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(request.inputs),
            key=lambda error: list(error.path),
        )
        if errors:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_capability_input", "message": errors[0].message},
            )
        inputs = coerce_capability_inputs(resolved_catalog, capability, request.inputs)
        try:
            result = await resolved_runner.run(resolved_catalog, capability_id, inputs)
        except CapabilityExecutionError as exc:
            status_code = {
                "capability_timeout": 504,
                "bid_notice_not_found": 404,
                "bid_requirements_not_found": 409,
                "invalid_bid_notice_id": 422,
            }.get(exc.code, 502)
            raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
        response = serialize_capability_result(
            result,
            max_objects=request.options.max_objects,
            include_property_provenance=request.options.include_property_provenance,
        )
        response["registry"] = (
            resolved_catalog.release.public_dict() if resolved_catalog.release else {"status": "draft"}
        )
        response["runtime_artifact"] = runtime_bundle.provenance() if runtime_bundle else None
        response["capability_version"] = {
            "id": capability.id,
            "version": capability.version,
            "definition_checksum": resolved_catalog.capability_checksums[
                (capability.id, capability.version)
            ],
        }
        response["execution"] = {
            "execution_id": execution_id,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "capability_id": capability.id,
            "capability_version": capability.version,
            "capability_checksum": resolved_catalog.capability_checksums[
                (capability.id, capability.version)
            ],
            "artifact_version": runtime_bundle.version if runtime_bundle else None,
            "artifact_checksum": runtime_bundle.bundle_checksum if runtime_bundle else None,
        }
        logger.info(
            "runtime capability executed",
            extra={
                "capability_id": capability_id,
                "registry_version": (
                    resolved_catalog.release.version if resolved_catalog.release else None
                ),
                "runtime_bundle_version": runtime_bundle.version if runtime_bundle else None,
                "runtime_bundle_checksum": (
                    runtime_bundle.bundle_checksum if runtime_bundle else None
                ),
            },
        )
        return response

    return app


def app_factory() -> FastAPI:
    return create_runtime_app()
