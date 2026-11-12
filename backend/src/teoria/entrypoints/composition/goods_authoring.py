"""Goods authoring composition; feature policies remain in their owning packages."""
from __future__ import annotations

from typing import TYPE_CHECKING
from fastapi import FastAPI
from teoria.domains.goods.expression_links.admin_router import create_goods_dictionary_router
from teoria.domains.goods.expression_links.registration_service import ExpressionRegistrationService
from teoria.domains.goods.expression_links.expression_link_service import ExpressionLinkService
from teoria.domains.goods.normalization.profiles.admin_router import create_normalization_profile_router
from teoria.domains.goods.normalization.profiles.service import NormalizationProfileService
from teoria.domains.goods.normalization.candidates.semantic_operation_repository import SemanticOperationRepository
from teoria.domains.goods.normalization.candidates.semantic_operation_service import SemanticOperationService

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_goods_authoring_routers(app: FastAPI, services: AdminServices):
    """Domain authoring consumes Ontology contracts; it is not a FormatID implementation."""
    dependency_reader = None
    if services.settings.goods_authoring_active:
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
        expressions = (ExpressionLinkService(services.settings.app_database_url,
            ontology_authoring=services.ontology_authoring_service) if services.settings.app_database_url else None)
        if profiles is not None and expressions is not None and services.binding_repository is not None:
            from teoria.domains.goods.normalization.ontology_impact import GoodsOntologyImpactService
            dependency_reader = GoodsOntologyImpactService(services.ontology_authoring_service, profiles,
                expressions, services.binding_repository, services.catalog).report
        from pathlib import Path
        import os
        from teoria.domains.goods.data_processing.storage.artifact_reader import verified_artifact
        from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store
        from teoria.domains.goods.normalization.meaning_proposals.interpretation_repository import InterpretationRepository
        from teoria.domains.goods.normalization.meaning_proposals.interpretation_service import InterpretationService
        from teoria.domains.goods.normalization.meaning_proposals.interpretation_router import create_interpretation_router

        object_root = os.getenv("TEORIA_SPECIFICATION_ARTIFACT_ROOT", "s3://teoria-artifacts")

        async def read_interpretation_artifact(reference):
            return await verified_artifact(reference, Path("/app/specification_artifacts"), object_root,
                                           limit=20 * 1024 * 1024)

        interpretations = (InterpretationService(
            InterpretationRepository(services.settings.app_database_url), profiles,
            services.ontology_authoring_service, read_interpretation_artifact,
            lambda: artifact_store(object_root)) if profiles else None)
        app.include_router(create_interpretation_router(interpretations, services.authorizer))
        app.include_router(
            create_normalization_profile_router(
                profiles, services.authorizer, operations
            )
        )
        app.include_router(
            create_goods_dictionary_router(
                ExpressionRegistrationService(services.settings.app_database_url)
                if services.settings.app_database_url
                else None,
                services.authorizer,
                expressions,
            )
        )
    return dependency_reader


def goods_ontology_migration_manifest(registry_path):
    """Compatibility manifest for the goods migration; selected by the goods composition."""
    root = registry_path.parent.parent if registry_path.parent.name == "contracts" else registry_path.parent
    return root / "authoring/ontology_migrations/pending/2026_10_goods_focus/ontology_v2.yaml"
