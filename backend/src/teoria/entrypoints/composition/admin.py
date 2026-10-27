from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from teoria.features.model_operations.admin_router import create_model_operations_router
from teoria.features.workflow_management.admin_router import create_workflow_router
from teoria.features.semantic_modeling.goods_dictionary.admin_router import create_goods_dictionary_router
from teoria.features.semantic_modeling.goods_dictionary.service import GoodsDictionaryService
from teoria.features.semantic_modeling.goods_dictionary.meaning_service import GoodsMeaningService

from teoria.features.metadata_management.intelligence.asset_assessment.admin_router import (
    create_asset_assessment_router,
)
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.semantic_modeling.binding.admin_router import create_binding_router
from teoria.features.runtime.context.admin_router import create_context_router
from teoria.features.metadata_management.intelligence.admin_router import (
    create_intelligence_router,
)
from teoria.features.metadata_management.catalog.admin_router import (
    create_metadata_router,
)
from teoria.features.semantic_modeling.ontology.admin_router import (
    create_ontology_authoring_router,
)
from teoria.features.semantic_modeling.ontology.migration_router import (
    create_ontology_migration_router,
)
from teoria.features.semantic_modeling.ontology.property_context_router import (
    create_property_context_router,
)
from teoria.features.semantic_modeling.registry.admin_router import (
    create_registry_router,
)
from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.features.runtime.context import ContextEngine
from teoria.features.runtime.context.repository import (
    BundleContextRepository,
    ContextRepository,
)
from teoria.features.runtime.context.runtime_client import ContextRuntimeClient
from teoria.features.runtime.context.service import ContextExecutionPolicy
from teoria.features.legal_information.admin_router import create_law_search_router
from teoria.features.legal_information.search import LawSearchReader
from teoria.features.goods_normalization.profiles.admin_router import (
    create_normalization_profile_router,
)
from teoria.features.goods_normalization.profiles.service import (
    NormalizationProfileService,
)
from teoria.features.goods_normalization.candidates.semantic_operation_repository import (
    SemanticOperationRepository,
)
from teoria.features.goods_normalization.candidates.semantic_operation_service import (
    SemanticOperationService,
)
from teoria.features.metadata_management.intelligence.asset_assessment.repository import (
    AssessmentRepository,
)
from teoria.features.metadata_management.intelligence.suggestions.repository import (
    SuggestionRepository,
)
from teoria.features.metadata_management.intelligence.suggestions.service import (
    SuggestionService,
)
from teoria.features.metadata_management.catalog.asset_context import (
    AssetApplicationReader,
    AssetContextService,
)
from teoria.integrations.openmetadata import OpenMetadataClient, OpenMetadataService
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
from teoria.features.access_control.policy import (
    PolicyEvaluator,
    OpaPolicyEvaluator,
    create_policy_evaluator,
)
from teoria.features.semantic_modeling.registry.loader import (
    RegistryCatalog,
    RegistryLoader,
)
from teoria.settings import Settings, bootstrap_settings


@dataclass(frozen=True)
class AdminServices:
    resources: list[Any] = field(default_factory=list, kw_only=True)
    settings: Settings
    catalog: RegistryCatalog
    authorizer: AdminAuthorizer
    metadata_service: OpenMetadataService | None
    binding_repository: BindingRepository | None
    suggestion_repository: SuggestionRepository | None
    ontology_authoring_service: OntologyAuthoringService | None
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
    resources = []
    authorizer = AdminAuthorizer(resolved_settings)
    resolved_policy_evaluator = policy_evaluator or create_policy_evaluator(
        resolved_settings
    )
    if policy_evaluator is None and isinstance(
        resolved_policy_evaluator, OpaPolicyEvaluator
    ):
        resources.append(resolved_policy_evaluator)
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
    resolved_ontology_authoring_service = (
        OntologyAuthoringService(resolved_settings.app_database_url)
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
        resources.append(resolved_metadata_service.client)
    context_runtime_client = None
    if context_engine is None and resolved_settings.context_runtime_api_token:
        context_runtime_client = ContextRuntimeClient(
            resolved_settings.context_runtime_api_url,
            resolved_settings.context_runtime_api_token,
            timeout_seconds=resolved_settings.context_runtime_timeout_seconds,
        )
        resources.append(context_runtime_client)
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
            context_runtime_client,
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
            resolved_ontology_authoring_service,
        )
        if resolved_suggestion_repository
        else None
    )
    return AdminServices(
        resources=resources,
        settings=resolved_settings,
        catalog=resolved_catalog,
        authorizer=authorizer,
        metadata_service=resolved_metadata_service,
        binding_repository=resolved_binding_repository,
        suggestion_repository=resolved_suggestion_repository,
        ontology_authoring_service=resolved_ontology_authoring_service,
        context_engine=resolved_context_engine,
        assessment_repository=resolved_assessment_repository,
        asset_context_service=resolved_asset_context_service,
        suggestion_service=resolved_suggestion_service,
        law_search_reader=law_search_reader
        or (
            LawSearchReader(resolved_settings.admin_data_database_url)
            if resolved_settings.admin_data_database_url
            else None
        ),
        ontology_migration_manifest=(
            (
                resolved_settings.registry_path.parent.parent
                if resolved_settings.registry_path.parent.name == "contracts"
                else resolved_settings.registry_path.parent
            )
            / "authoring/ontology_migrations/pending/2026_10_goods_focus/ontology_v2.yaml"
        ),
    )


def install_admin_routers(app: FastAPI, services: AdminServices) -> None:
    model_client = httpx.AsyncClient(timeout=15)
    services.resources.append(model_client)
    app.include_router(create_model_operations_router(authorizer=services.authorizer, client=model_client,
        enabled=services.settings.model_operations_enabled,
        prefect_url=services.settings.model_prefect_url, prefect_auth=services.settings.model_prefect_auth,
        mlflow_url=services.settings.model_mlflow_url, inference_url=services.settings.model_inference_url,
        inference_token=services.settings.demo_inference_token))
    app.include_router(create_workflow_router(authorizer=services.authorizer, client=model_client,
        prefect_url=services.settings.model_prefect_url, prefect_auth=services.settings.model_prefect_auth,
        mlops_enabled=services.settings.model_operations_enabled,
        inference_token=services.settings.demo_inference_token))
    profiles = (
        NormalizationProfileService(
            services.settings.app_database_url,
            ontology_authoring=services.ontology_authoring_service,
        )
        if services.settings.app_database_url
        else None
    )
    operations = (
        SemanticOperationService(
            profiles,
            SemanticOperationRepository(services.settings.app_database_url),
            services.ontology_authoring_service,
        )
        if profiles
        else None
    )
    app.include_router(
        create_normalization_profile_router(profiles, services.authorizer, operations)
    )
    app.include_router(create_goods_dictionary_router(
        GoodsDictionaryService(services.settings.app_database_url) if services.settings.app_database_url else None,
        services.authorizer,
        GoodsMeaningService(services.settings.app_database_url) if services.settings.app_database_url else None,
    ))
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
        create_law_search_router(services.law_search_reader, services.authorizer)
    )
    app.include_router(create_property_context_router(services.binding_repository))
    app.include_router(
        create_binding_router(
            services.binding_repository, services.authorizer, services.catalog
        )
    )
    app.include_router(
        create_ontology_authoring_router(
            services.ontology_authoring_service, services.authorizer
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
