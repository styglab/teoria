"""Model operations composition; feature policies remain in their owning packages."""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI

from teoria.entrypoints.composition.workflow_catalog import workflow_catalog
from teoria.entrypoints.composition.workflow_management import prepare_workflow_run
from teoria.platform.mlops.serving_router import create_serving_router
from teoria.platform.mlops.admin_router import create_model_operations_router
from teoria.platform.mlops.image_registry_router import create_image_registry_router
from teoria.integrations.image_registry import ImageRegistryClient

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_model_operations_router(
    app: FastAPI, services: AdminServices, client: httpx.AsyncClient
) -> None:
    settings = services.settings
    registry_client = client
    if settings.image_registry_url and settings.image_registry_ca_pem:
        trust = ssl.create_default_context()
        trust.load_verify_locations(cadata=settings.image_registry_ca_pem)
        registry_client = httpx.AsyncClient(timeout=15, verify=trust)
        services.resources.append(registry_client)
    registry = (
        ImageRegistryClient(
            registry_client,
            url=settings.image_registry_url,
            provider=settings.image_registry_provider,
            project=settings.image_registry_project,
            public_host=settings.image_registry_public_host,
            username=settings.image_registry_username,
            password=settings.image_registry_password,
        )
        if settings.image_registry_url
        else None
    )
    app.include_router(
        create_image_registry_router(authorizer=services.authorizer, registry=registry)
    )
    catalog = workflow_catalog(
        services.settings.model_operations_enabled,
        semantic_enabled=False,
        formatid_enabled=False,
        legal_enabled=False,
    )
    app.include_router(
        create_model_operations_router(
            authorizer=services.authorizer,
            client=client,
            enabled=services.settings.model_operations_enabled,
            workflow_catalog=catalog,
            prepare_run=prepare_workflow_run(catalog),
            prefect_url=services.settings.model_prefect_url,
            prefect_auth=services.settings.model_prefect_auth,
            mlflow_url=services.settings.model_mlflow_url,
        )
    )

    app.include_router(
        create_serving_router(
            authorizer=services.authorizer,
            client=client,
            database_url=settings.app_database_url,
            enabled=settings.model_operations_enabled,
        )
    )
