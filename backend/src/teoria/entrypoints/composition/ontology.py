"""Ontology composition; feature policies remain in their owning packages."""
from __future__ import annotations

from typing import TYPE_CHECKING
from fastapi import FastAPI
from teoria.platform.ontology.bindings.admin_router import create_binding_router
from teoria.platform.ontology.runtime.context.admin_router import create_context_router
from teoria.platform.ontology.authoring.admin_router import create_ontology_authoring_router
from teoria.platform.ontology.contracts.ontology_migration_router import create_ontology_migration_router
from teoria.platform.ontology.bindings.property_context_router import create_property_context_router
from teoria.platform.ontology.contracts.admin_router import create_registry_router

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_ontology_routers(app: FastAPI, services: AdminServices, dependency_reader) -> None:
    """Meaning authoring and published execution contracts remain separate from app routes."""
    if not (
        services.settings.ontology_enabled
        or services.settings.formatid_enabled
    ):
        return
    app.include_router(create_property_context_router(services.binding_repository))
    app.include_router(
        create_binding_router(
            services.binding_repository, services.authorizer, services.catalog
        )
    )
    app.include_router(
        create_ontology_authoring_router(
            services.ontology_authoring_service, services.authorizer, dependency_reader=dependency_reader,
        )
    )
    if not services.settings.ontology_enabled:
        return
    app.include_router(
        create_context_router(services.context_engine, services.authorizer)
    )

    app.include_router(create_registry_router(services.catalog))
    app.include_router(
        create_ontology_migration_router(
            services.catalog,
            services.ontology_migration_manifest,
            services.settings.app_database_url,
        )
    )
