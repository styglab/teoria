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
    if (
        services.settings.semantic_modeling_enabled
        or services.settings.formatid_enabled
    ):
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
