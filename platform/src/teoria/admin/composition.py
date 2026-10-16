from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from teoria.admin.asset_assessment_api import create_asset_assessment_router
from teoria.admin.auth import AdminAuthorizer
from teoria.admin.binding_api import create_binding_router
from teoria.admin.context_api import create_context_router
from teoria.admin.intelligence_api import create_intelligence_router
from teoria.admin.metadata_api import create_metadata_router
from teoria.admin.ontology_authoring_api import create_ontology_authoring_router
from teoria.admin.ontology_migration_api import create_ontology_migration_router
from teoria.admin.property_context_api import create_property_context_router
from teoria.admin.registry_api import create_registry_router
from teoria.binding.repository import BindingRepository
from teoria.context import ContextEngine
from teoria.context.repository import BundleContextRepository, ContextRepository
from teoria.context.runtime_client import ContextRuntimeClient
from teoria.context.service import ContextExecutionPolicy
from teoria.domains.legal_information.admin_api import create_law_search_router
from teoria.domains.legal_information.search import LawSearchReader
from teoria.domains.public_procurement.metadata_operations import AssetCollectionReader
from teoria.domains.public_procurement.ontology_migration import (
    applied_ontology_migration_manifest,
)
from teoria.intelligence.asset_assessment.repository import AssessmentRepository
from teoria.intelligence.suggestions.repository import SuggestionRepository
from teoria.intelligence.suggestions.service import SuggestionService
from teoria.metadata.asset_context import AssetApplicationReader, AssetContextService
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataService
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.policy import PolicyEvaluator, create_policy_evaluator
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.settings import Settings, bootstrap_settings


@dataclass(frozen=True)
class AdminServices:
    settings: Settings
    catalog: RegistryCatalog
    authorizer: AdminAuthorizer
    metadata_service: OpenMetadataService | None
    binding_repository: BindingRepository | None
    suggestion_repository: SuggestionRepository | None
    ontology_authoring_repository: OntologyAuthoringRepository | None
    context_engine: ContextEngine | None
    assessment_repository: AssessmentRepository | None
    asset_context_service: AssetContextService | None
    suggestion_service: SuggestionService | None
    law_search_reader: LawSearchReader | None
    ontology_migration_manifest: Path


def create_admin_services(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    metadata_service: OpenMetadataService | None = None,
    binding_repository: BindingRepository | None = None,
    suggestion_repository: SuggestionRepository | None = None,
    context_engine: ContextEngine | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
    assessment_repository: AssessmentRepository | None = None,
    asset_context_service: AssetContextService | None = None,
    suggestion_service: SuggestionService | None = None,
    law_search_reader: LawSearchReader | None = None,
) -> AdminServices:
    resolved_settings = settings or bootstrap_settings()
    authorizer = AdminAuthorizer(resolved_settings)
    resolved_policy_evaluator = policy_evaluator or create_policy_evaluator(
        resolved_settings
    )
    resolved_catalog = catalog or RegistryLoader(resolved_settings.registry_path).load()
    resolved_metadata_service = metadata_service
    resolved_binding_repository = binding_repository or (
        BindingRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url
        else None
    )
    resolved_suggestion_repository = suggestion_repository or (
        SuggestionRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url
        else None
    )
    resolved_ontology_authoring_repository = (
        OntologyAuthoringRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url
        else None
    )
    if resolved_metadata_service is None and resolved_settings.openmetadata_enabled:
        resolved_metadata_service = OpenMetadataService(
            OpenMetadataClient(
                resolved_settings.openmetadata_base_url,
                resolved_settings.openmetadata_auth_token,
                timeout_seconds=resolved_settings.openmetadata_timeout_seconds,
                verify_ssl=resolved_settings.openmetadata_verify_ssl,
            ),
            base_url=resolved_settings.openmetadata_base_url,
            database_service=resolved_settings.openmetadata_database_service,
        )
    runtime_context_repository = (
        BundleContextRepository.from_path(resolved_settings.runtime_artifact_path)
        if resolved_settings.runtime_artifact_path is not None
        else BundleContextRepository.from_store(
            resolved_settings.runtime_artifact_store
        )
        if resolved_settings.runtime_artifact_store is not None
        else ContextRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url
        else None
    )
    resolved_context_engine = context_engine or (
        ContextEngine(
            runtime_context_repository,
            resolved_metadata_service.client if resolved_metadata_service else None,
            ContextRuntimeClient(
                resolved_settings.context_runtime_api_url,
                resolved_settings.context_runtime_api_token,
                timeout_seconds=resolved_settings.context_runtime_timeout_seconds,
            )
            if resolved_settings.context_runtime_api_token
            else None,
            ContextExecutionPolicy(
                max_period_years=resolved_settings.context_max_period_years,
                max_pages=resolved_settings.context_max_pages,
            ),
            resolved_policy_evaluator,
        )
        if runtime_context_repository is not None
        else None
    )
    resolved_assessment_repository = assessment_repository or (
        AssessmentRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url
        else None
    )
    resolved_asset_context_service = asset_context_service
    if (
        resolved_asset_context_service is None
        and resolved_metadata_service
        and getattr(resolved_metadata_service, "client", None)
    ):
        resolved_asset_context_service = AssetContextService(
            resolved_metadata_service.client,
            database_service=resolved_metadata_service.database_service,
            operations_reader=AssetCollectionReader(
                resolved_settings.admin_data_database_url
            )
            if resolved_settings.admin_data_database_url
            else None,
            application_reader=AssetApplicationReader(
                resolved_settings.app_database_url
            )
            if resolved_settings.app_database_url
            else None,
        )
    resolved_suggestion_service = suggestion_service or (
        SuggestionService(
            resolved_suggestion_repository,
            resolved_metadata_service.client if resolved_metadata_service else None,
            resolved_binding_repository,
            resolved_ontology_authoring_repository,
        )
        if resolved_suggestion_repository
        else None
    )
    resolved_law_search_reader = law_search_reader or (
        LawSearchReader(resolved_settings.admin_data_database_url)
        if resolved_settings.admin_data_database_url
        else None
    )
    return AdminServices(
        settings=resolved_settings,
        catalog=resolved_catalog,
        authorizer=authorizer,
        metadata_service=resolved_metadata_service,
        binding_repository=resolved_binding_repository,
        suggestion_repository=resolved_suggestion_repository,
        ontology_authoring_repository=resolved_ontology_authoring_repository,
        context_engine=resolved_context_engine,
        assessment_repository=resolved_assessment_repository,
        asset_context_service=resolved_asset_context_service,
        suggestion_service=resolved_suggestion_service,
        law_search_reader=resolved_law_search_reader,
        ontology_migration_manifest=applied_ontology_migration_manifest(
            resolved_settings.registry_path
        ),
    )


def install_admin_routers(app: FastAPI, services: AdminServices) -> None:
    app.include_router(
        create_asset_assessment_router(
            services.assessment_repository,
            getattr(services.metadata_service, "client", None),
            services.authorizer,
            enabled=bool(
                services.settings.assessment_enabled
                and services.settings.assessment_model_url
            ),
            model_name=services.settings.assessment_model_name,
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
    app.include_router(
        create_law_search_router(
            services.law_search_reader,
            services.authorizer,
        )
    )
    app.include_router(create_property_context_router(services.binding_repository))
    app.include_router(
        create_binding_router(
            services.binding_repository, services.authorizer, services.catalog
        )
    )
    app.include_router(
        create_ontology_authoring_router(
            services.ontology_authoring_repository, services.authorizer
        )
    )
    app.include_router(
        create_intelligence_router(
            services.suggestion_service,
            services.authorizer,
        )
    )
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
