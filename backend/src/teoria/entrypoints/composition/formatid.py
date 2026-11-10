"""Wire FormatID routes to goods processing and approval services."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from teoria.apps.formatid.router import create_processing_workspace_router
from teoria.domains.goods.expression_links.expression_link_service import (
    ExpressionLinkService,
)

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_formatid_routers(app: FastAPI, services: AdminServices):
    """Compose the app; goods services own processing and pinned criteria."""
    import os

    from teoria.domains.goods.data_processing.queries import ProcessingQueries
    from teoria.domains.goods.data_processing.storage.artifact_reader import (
        verified_artifact,
    )
    from teoria.domains.goods.data_processing.storage.artifact_store import (
        artifact_store,
    )
    from teoria.domains.goods.normalization.processing_criteria_repository import (
        ApplicationStandardsRepository,
    )
    from teoria.domains.goods.normalization.processing_criteria_router import (
        create_application_standards_router,
    )
    from teoria.domains.goods.normalization.processing_criteria_service import (
        ApplicationStandardsService,
    )

    runtime_query = None
    if (
        services.settings.formatid_enabled
        and services.settings.context_runtime_api_token
    ):
        import httpx
        from fastapi import HTTPException

        from teoria.domains.goods.runtime import CAPABILITY_ID
        from teoria.platform.ontology.runtime.context.runtime_client import (
            ContextRuntimeClient,
            ContextRuntimeError,
        )

        client = httpx.AsyncClient(
            timeout=services.settings.context_runtime_timeout_seconds
        )
        services.resources.append(client)
        runtime = ContextRuntimeClient(
            services.settings.context_runtime_api_url,
            services.settings.context_runtime_api_token,
            client=client,
        )

        async def query_requirements(principal, inputs):
            try:
                return await runtime.execute(
                    CAPABILITY_ID,
                    inputs,
                    actor=principal.actor,
                    roles=principal.roles,
                    service="formatid",
                )
            except ContextRuntimeError as exc:
                status = exc.status_code if exc.status_code in {403, 404, 409} else 503
                raise HTTPException(
                    status, detail={"code": exc.code or "goods_runtime_unavailable"}
                ) from None
            except (httpx.HTTPError, ValueError):
                raise HTTPException(
                    503, detail={"code": "goods_runtime_unavailable"}
                ) from None

        runtime_query = query_requirements

    application_standards = None
    if (
        services.settings.formatid_enabled
        and services.settings.app_database_url
        and services.settings.admin_data_database_url
    ):
        object_root = os.getenv(
            "TEORIA_SPECIFICATION_ARTIFACT_ROOT", "s3://teoria-artifacts"
        )

        async def read_standard(reference):
            return await verified_artifact(
                reference, Path("/app/specification_artifacts"), object_root
            )

        application_standards = ApplicationStandardsService(
            ApplicationStandardsRepository(services.settings.app_database_url),
            ProcessingQueries(services.settings.admin_data_database_url),
            ExpressionLinkService(
                services.settings.app_database_url,
                ontology_authoring=services.ontology_authoring_service,
            ),
            read_standard,
            lambda: artifact_store(object_root),
        )
    app.include_router(
        create_application_standards_router(application_standards, services.authorizer)
    )
    app.include_router(
        create_processing_workspace_router(
            authorizer=services.authorizer,
            database_url=services.settings.admin_data_database_url
            if services.settings.formatid_enabled
            else None,
            runtime_query=runtime_query,
            uploads_enabled=services.settings.formatid_enabled
            and services.settings.specification_upload_enabled,
        )
    )
    return application_standards
