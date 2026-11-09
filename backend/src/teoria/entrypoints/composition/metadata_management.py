"""Metadata management composition; feature policies remain in their owning packages."""
from __future__ import annotations

from typing import TYPE_CHECKING
from teoria.platform.data.metadata.intelligence.asset_assessment.model_client import assessment_model_identity
from fastapi import FastAPI
from teoria.platform.data.metadata.intelligence.asset_assessment.admin_router import create_asset_assessment_router
from teoria.platform.data.metadata.catalog.admin_router import create_metadata_router

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_metadata_routers(app: FastAPI, services: AdminServices) -> None:
    """Technical metadata stays authoritative in OpenMetadata."""
    if services.settings.semantic_modeling_enabled:
        app.include_router(
            create_asset_assessment_router(
                services.assessment_repository,
                getattr(services.metadata_service, "client", None),
                services.authorizer,
                enabled=bool(services.settings.assessment_enabled),
                model_name=assessment_model_identity(
                    services.settings.assessment_codex_model
                ),
            )
        )
    app.include_router(
        create_metadata_router(
            services.metadata_service,
            services.authorizer,
            services.asset_context_service,
            public_read=services.settings.admin_metadata_public_read,
        )
    )
