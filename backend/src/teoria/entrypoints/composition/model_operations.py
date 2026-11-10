"""Model operations composition; feature policies remain in their owning packages."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import httpx
from fastapi import FastAPI

from teoria.entrypoints.composition.workflow_catalog import workflow_catalog
from teoria.entrypoints.composition.workflow_management import prepare_workflow_run
from teoria.examples.customer_churn import MODEL_NAME
from teoria.examples.customer_churn.admin_router import (
    create_customer_churn_router,
    describe_models,
)
from teoria.platform.mlops.admin_router import create_model_operations_router
from teoria.platform.mlops.image_registry_router import create_image_registry_router
from teoria.integrations.image_registry import ImageRegistryClient

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_model_operations_router(
    app: FastAPI, services: AdminServices, client: httpx.AsyncClient
) -> None:
    settings = services.settings
    registry = (
        ImageRegistryClient(
            client,
            url=settings.image_registry_url,
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
        include_internal=True,
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
            default_model_name=MODEL_NAME,
            parameter_names=frozenset(
                {
                    "dataset_version",
                    "dataset_sha256",
                    "split_seed",
                    "personal_attributes_in_features",
                }
            ),
            model_context=partial(
                describe_models, client, services.settings.model_inference_url
            ),
            inference_token=services.settings.demo_inference_token,
        )
    )

    app.include_router(
        create_customer_churn_router(
            authorizer=services.authorizer,
            client=client,
            enabled=services.settings.model_operations_enabled,
            inference_url=services.settings.model_inference_url,
            inference_token=services.settings.demo_inference_token,
        )
    )
