"""Workflow management composition; feature policies remain in their owning packages."""

from __future__ import annotations

from typing import TYPE_CHECKING
import httpx
from fastapi import FastAPI, HTTPException
from teoria.platform.workflow_management.admin_router import create_workflow_router
from teoria.domains.goods.workflows.manifest_validation import validate_manifest
from teoria.entrypoints.composition.workflow_catalog import workflow_catalog
from teoria.platform.mlops.contracts import validate_execution
from pydantic import ValidationError

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_workflow_management_router(
    app: FastAPI,
    services: AdminServices,
    client: httpx.AsyncClient,
    application_standards,
) -> None:
    catalog = workflow_catalog(
        services.settings.model_operations_enabled,
        semantic_enabled=services.settings.semantic_modeling_enabled,
        formatid_enabled=services.settings.formatid_enabled,
        legal_enabled=services.settings.legal_information_enabled,
    )
    app.include_router(
        create_workflow_router(
            catalog=catalog,
            prepare_run=prepare_workflow_run(catalog, application_standards),
            authorizer=services.authorizer,
            client=client,
            prefect_url=services.settings.model_prefect_url,
            prefect_auth=services.settings.model_prefect_auth,
        )
    )


def prepare_workflow_run(catalog, application_standards=None):
    """Connect enabled workflows to their input and ownership policies."""

    async def prepare(pipeline_id, payload, principal):
        input_kind = catalog[pipeline_id][2]
        if (payload.manifest is not None) != (input_kind == "manifest"):
            raise HTTPException(422, "manifest_required_or_not_applicable")
        if payload.deploy is not None and input_kind != "model":
            raise HTTPException(422, "deploy_not_applicable")
        if input_kind == "version" and payload.model_version is None:
            raise HTTPException(422, "model_version_required")
        if input_kind != "version" and payload.model_version is not None:
            raise HTTPException(422, "model_version_not_applicable")
        is_execution = input_kind in {"training", "serving", "stop-serving"}
        if (payload.execution is not None) != is_execution:
            raise HTTPException(422, "execution_required_or_not_applicable")
        parameters = (
            {"requested_by": principal.actor}
            if catalog[pipeline_id][1] == "모델"
            else {}
        )
        if is_execution:
            try:
                parameters["execution"] = validate_execution(input_kind, payload.execution)
            except (ValidationError, ValueError):
                raise HTTPException(422, "invalid_model_execution_contract") from None
        if payload.manifest is not None:
            parameters["manifest"] = await validate_manifest(
                pipeline_id,
                payload.manifest,
                principal,
                application_standards,
            )
        if input_kind == "model":
            parameters["deploy"] = (
                payload.deploy if payload.deploy is not None else False
            )
        if payload.model_version is not None:
            parameters["model_version"] = payload.model_version
        return parameters

    return prepare
