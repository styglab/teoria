"""Wire FormatID routes to goods processing and approval services."""
from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path
from fastapi import FastAPI
from teoria.apps.formatid.router import create_processing_workspace_router
from teoria.domains.goods.expression_links.expression_link_service import ExpressionLinkService

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_formatid_routers(app: FastAPI, services: AdminServices):
    """Compose the app; goods services own processing and pinned criteria."""
    import os
    from teoria.domains.goods.normalization.processing_criteria_repository import ApplicationStandardsRepository
    from teoria.domains.goods.normalization.processing_criteria_service import ApplicationStandardsService
    from teoria.domains.goods.normalization.processing_criteria_router import create_application_standards_router
    from teoria.domains.goods.data_processing.queries import ProcessingQueries
    from teoria.domains.goods.data_processing.storage.artifact_reader import verified_artifact
    from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store

    application_standards = None
    if services.settings.formatid_enabled and services.settings.app_database_url and services.settings.admin_data_database_url:
        object_root = os.getenv('TEORIA_SPECIFICATION_ARTIFACT_ROOT','s3://teoria-artifacts')
        async def read_standard(reference):
            return await verified_artifact(reference,Path('/app/specification_artifacts'),object_root)
        application_standards = ApplicationStandardsService(
            ApplicationStandardsRepository(services.settings.app_database_url),
            ProcessingQueries(services.settings.admin_data_database_url),
            ExpressionLinkService(services.settings.app_database_url, ontology_authoring=services.ontology_authoring_service), read_standard,
            lambda: artifact_store(object_root))
    app.include_router(create_application_standards_router(application_standards,services.authorizer))
    app.include_router(
        create_processing_workspace_router(
            authorizer=services.authorizer,
            database_url=services.settings.admin_data_database_url
            if services.settings.formatid_enabled
            else None,
            uploads_enabled=services.settings.formatid_enabled
            and services.settings.specification_upload_enabled,
        )
    )
    return application_standards
