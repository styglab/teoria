from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.platform.ontology.bindings.repository import BindingRepository
from teoria.platform.ontology.runtime.context import ContextEngine
from teoria.platform.ontology.runtime.context.repository import (
    BundleContextRepository,
    ContextRepository,
)
from teoria.platform.ontology.runtime.context.runtime_client import ContextRuntimeClient
from teoria.platform.ontology.runtime.context.service import ContextExecutionPolicy
from teoria.domains.legal_information.search import LawSearchReader
from teoria.platform.data.metadata.intelligence.asset_assessment.repository import (
    AssessmentRepository,
)
from teoria.platform.data.metadata.intelligence.suggestions.repository import (
    SuggestionRepository,
)
from teoria.platform.data.metadata.intelligence.suggestions.service import (
    SuggestionService,
)
from teoria.platform.data.metadata.catalog.asset_context import (
    AssetApplicationReader,
    AssetContextService,
)
from teoria.integrations.openmetadata import OpenMetadataClient
from teoria.integrations.openmetadata import OpenMetadataService
from teoria.platform.ontology.authoring.service import OntologyAuthoringService
from teoria.platform.access_control.policy import (
    PolicyEvaluator,
    OpaPolicyEvaluator,
    create_policy_evaluator,
)
from teoria.platform.ontology.contracts.loader import (
    RegistryCatalog,
    RegistryLoader,
)
from teoria.settings import Settings
from teoria.settings import bootstrap_settings

from teoria.entrypoints.composition.formatid import install_formatid_routers
from teoria.entrypoints.composition.goods_authoring import install_goods_authoring_routers
from teoria.entrypoints.composition.metadata_management import install_metadata_routers
from teoria.entrypoints.composition.legal_information import install_legal_routers
from teoria.entrypoints.composition.semantic_modeling import install_semantic_routers
from teoria.entrypoints.composition.model_operations import install_model_operations_router
from teoria.entrypoints.composition.workflow_management import install_workflow_management_router


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
    resources.append(authorizer)
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
    if (
        resolved_metadata_service is None
        and resolved_settings.semantic_modeling_enabled
        and resolved_settings.openmetadata_enabled
    ):
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
    if (
        resolved_settings.semantic_modeling_enabled
        and context_engine is None
        and resolved_settings.context_runtime_api_token
    ):
        context_runtime_client = ContextRuntimeClient(
            resolved_settings.context_runtime_api_url,
            resolved_settings.context_runtime_api_token,
            timeout_seconds=resolved_settings.context_runtime_timeout_seconds,
        )
        resources.append(context_runtime_client)
    runtime_context_repository = (
        None
        if not resolved_settings.semantic_modeling_enabled
        else (
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
    """Compose platform features, domain authoring and business applications explicitly."""
    application_standards = install_formatid_routers(app, services)
    operations_client = httpx.AsyncClient(timeout=15)
    services.resources.append(operations_client)
    install_model_operations_router(app, services, operations_client)
    install_workflow_management_router(app, services, operations_client, application_standards)
    dependency_reader = install_goods_authoring_routers(app, services)
    install_metadata_routers(app, services)
    install_legal_routers(app, services)
    install_semantic_routers(app, services, dependency_reader)
