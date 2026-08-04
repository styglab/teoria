from __future__ import annotations

import hmac
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, Field

from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider
from teoria.config import Settings, bootstrap_settings
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.runtime.capability.presentation import serialize_capability_result
from teoria.runtime.capability.runner import CapabilityExecutionError, CapabilityRunner
from teoria.runtime.capability.schema import capability_input_schema, coerce_capability_inputs


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
    resolved_catalog = catalog or RegistryLoader(resolved_settings.registry_path).load()
    resolved_runner = runner or CapabilityRunner(
        ProviderExecutor(
            timeout_seconds=resolved_settings.source_timeout_seconds,
            max_attempts=resolved_settings.source_max_attempts,
            secret_provider=EnvironmentSecretProvider(),
        ),
        timeout_seconds=resolved_settings.capability_timeout_seconds,
        max_pages=resolved_settings.source_max_pages,
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

    @app.get("/v1/capabilities", dependencies=[Depends(authorize)])
    async def list_capabilities() -> dict[str, list[dict[str, Any]]]:
        return {
            "capabilities": [
                {
                    "id": capability.id,
                    "name": capability.name,
                    "description": capability.description,
                    "returns": capability.returns,
                    "input_schema": capability_input_schema(resolved_catalog, capability),
                }
                for capability in resolved_catalog.capabilities.values()
            ]
        }

    @app.post("/v1/capabilities/{capability_id}:execute", dependencies=[Depends(authorize)])
    async def execute_capability(
        capability_id: str,
        request: CapabilityExecutionRequest,
    ) -> dict[str, Any]:
        capability = resolved_catalog.capabilities.get(capability_id)
        if capability is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_capability", "message": capability_id})
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
            status_code = 504 if exc.code == "capability_timeout" else 502
            raise HTTPException(status_code=status_code, detail=exc.to_dict()) from exc
        return serialize_capability_result(
            result,
            max_objects=request.options.max_objects,
            include_property_provenance=request.options.include_property_provenance,
        )

    return app


def app_factory() -> FastAPI:
    return create_runtime_app()
