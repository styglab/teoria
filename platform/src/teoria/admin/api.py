from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from teoria.admin.ontology_graph import build_runtime_contract_graph
from teoria.admin.overview import build_registry_overview
from teoria.admin.bid_check import BidCheckReader
from teoria.admin.metadata_api import create_metadata_router
from teoria.admin.semantic_api import create_semantic_router
from teoria.admin.intelligence_api import create_intelligence_router
from teoria.admin.auth import AdminAuthorizer
from teoria.admin.binding_api import create_binding_router
from teoria.admin.ontology_authoring_api import create_ontology_authoring_router
from teoria.admin.context_api import create_context_router
from teoria.binding.repository import BindingRepository
from teoria.context import ContextEngine
from teoria.context.repository import ContextRepository
from teoria.context.runtime_client import ContextRuntimeClient
from teoria.intelligence.repository import SuggestionRepository
from teoria.intelligence.service import SuggestionService
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.config import Settings, bootstrap_settings
from teoria.metadata.openmetadata import OpenMetadataClient, OpenMetadataService
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.validator import RegistryValidator


def create_admin_app(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    bid_check_reader: BidCheckReader | None = None,
    metadata_service: OpenMetadataService | None = None,
    binding_repository: BindingRepository | None = None,
    suggestion_repository: SuggestionRepository | None = None,
    context_engine: ContextEngine | None = None,
) -> FastAPI:
    resolved_settings = settings or bootstrap_settings()
    authorizer = AdminAuthorizer(resolved_settings)
    resolved_catalog = catalog or RegistryLoader(resolved_settings.registry_path).load()
    resolved_bid_reader = bid_check_reader or (
        BidCheckReader(resolved_settings.admin_data_database_url)
        if resolved_settings.admin_data_database_url else None
    )
    resolved_metadata_service = metadata_service
    resolved_binding_repository = binding_repository or (
        BindingRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url else None
    )
    resolved_suggestion_repository = suggestion_repository or (
        SuggestionRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url else None
    )
    resolved_ontology_authoring_repository = (
        OntologyAuthoringRepository(resolved_settings.app_database_url)
        if resolved_settings.app_database_url else None
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
    resolved_context_engine = context_engine or (
        ContextEngine(
            ContextRepository(resolved_settings.app_database_url),
            resolved_metadata_service.client if resolved_metadata_service else None,
            ContextRuntimeClient(
                resolved_settings.context_runtime_api_url,
                resolved_settings.context_runtime_api_token,
                timeout_seconds=resolved_settings.context_runtime_timeout_seconds,
            ) if resolved_settings.context_runtime_api_token else None,
        )
        if resolved_settings.app_database_url else None
    )
    app = FastAPI(
        title="Teoria Admin API",
        version="1.0.0",
        root_path=resolved_settings.admin_api_root_path,
    )
    if resolved_settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.include_router(create_metadata_router(resolved_metadata_service))
    app.include_router(create_semantic_router(resolved_binding_repository))
    app.include_router(create_binding_router(resolved_binding_repository, authorizer, resolved_catalog))
    app.include_router(create_ontology_authoring_router(resolved_ontology_authoring_repository, authorizer))
    app.include_router(create_intelligence_router(
        resolved_suggestion_repository,
        SuggestionService(
            resolved_suggestion_repository,
            resolved_metadata_service.client if resolved_metadata_service else None,
            resolved_binding_repository,
        ) if resolved_suggestion_repository else None,
        authorizer,
    ))
    app.include_router(create_context_router(resolved_context_engine))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/admin/overview")
    async def overview() -> dict[str, Any]:
        return build_registry_overview(resolved_catalog)

    @app.get("/v1/admin/registry-release")
    async def registry_release() -> dict[str, str | None]:
        if resolved_catalog.release is None:
            return {"version": None, "git_commit": None, "checksum": None, "published_at": None, "status": "draft"}
        return resolved_catalog.release.public_dict()

    def runtime_contract_summaries() -> list[dict[str, Any]]:
        return [
                {
                    "id": ontology.id,
                    "name": ontology.name,
                    "description": ontology.description,
                    "object_count": len(ontology.object_types),
                    "link_count": len(ontology.link_types),
                }
                for ontology in resolved_catalog.runtime_contracts.values()
            ]

    @app.get("/v1/admin/runtime-contracts")
    async def list_runtime_contracts() -> dict[str, list[dict[str, Any]]]:
        return {"runtime_contracts": runtime_contract_summaries()}

    @app.get("/v1/admin/ontology-migration")
    async def ontology_migration() -> dict[str, Any]:
        manifest_path = resolved_settings.registry_path.parent / "ontology-migrations" / "ontology-v2.yaml"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail={"code": "ontology_migration_manifest_not_found"})
        return build_migration_report(
            resolved_catalog,
            OntologyMigrationManifest.load(manifest_path),
            application_database_url=resolved_settings.app_database_url,
        )

    @app.get("/v1/admin/capabilities")
    async def list_capabilities() -> dict[str, list[dict[str, Any]]]:
        return {
            "capabilities": [
                {
                    "id": capability.id,
                    "name": capability.name or capability.id,
                    "description": capability.description,
                    "kind": capability.kind,
                    "processor": capability.processor,
                    "effects": capability.effects.model_dump(),
                    "inputs": list(capability.inputs),
                    "steps": [step.call for step in capability.steps],
                    "returns": capability.returns,
                }
                for capability in resolved_catalog.capabilities.values()
            ]
        }

    @app.get("/v1/admin/eligibility-rules")
    async def list_eligibility_rules() -> dict[str, list[dict[str, Any]]]:
        return {
            "eligibility_rules": [
                {
                    "id": rule.id,
                    "name": rule.name or rule.id,
                    "description": rule.description,
                    "version": rule.version,
                    "evaluator": rule.evaluator,
                    "evaluability": rule.evaluability,
                    "arguments": [item.model_dump() for item in rule.arguments],
                    "required_facts": rule.required_facts,
                    "missing_fact_result": rule.missing_fact_result,
                }
                for rule in resolved_catalog.eligibility_rules.values()
            ]
        }

    @app.get("/v1/admin/sources")
    async def list_sources() -> dict[str, list[dict[str, Any]]]:
        sources = []
        for registry in resolved_catalog.sources.values():
            source = registry.source
            is_database = source.type == "database"
            sources.append(
                {
                    "id": source.id,
                    "name": source.name or source.id,
                    "description": getattr(source, "description", None),
                    "type": source.type,
                    "provider": None if is_database else source.provider.organization,
                    "items": len(source.relations) if is_database else len(source.operations),
                    "item_label": "relations" if is_database else "operations",
                }
            )
        return {"sources": sources}

    @app.get("/v1/admin/mappings")
    async def list_mappings() -> dict[str, list[dict[str, Any]]]:
        return {
            "mappings": [
                {
                    "id": mapping.id,
                    "name": mapping.name or mapping.id,
                    "description": mapping.description,
                    "ontology": mapping.ontology,
                    "binding_count": sum(len(bindings) for bindings in mapping.bindings.values()),
                    "property_count": len(mapping.bindings),
                }
                for mapping in resolved_catalog.mappings.values()
            ]
        }

    @app.get("/v1/admin/lineage")
    async def lineage() -> dict[str, list[dict[str, Any]]]:
        links: list[dict[str, Any]] = []
        for mapping in resolved_catalog.mappings.values():
            source_ids: set[str] = set()
            for bindings in mapping.bindings.values():
                for binding in bindings:
                    fields = [binding.field] if isinstance(binding.field, str) else list(binding.field.values())
                    source_ids.update(field.split(".", 1)[0] for field in fields)
            links.extend(
                {"from": source_id, "via": mapping.id, "to": mapping.ontology, "kind": "mapping"}
                for source_id in sorted(source_ids)
            )
        for capability in resolved_catalog.capabilities.values():
            source_ids = sorted({step.call.split(".", 1)[0] for step in capability.steps})
            ontology_ids = sorted({item.split(".", 1)[0] for item in capability.returns})
            links.extend(
                {"from": source_id, "via": capability.id, "to": ontology_id, "kind": "capability"}
                for source_id in source_ids
                for ontology_id in ontology_ids
            )
        return {"links": links}

    @app.get("/v1/admin/validation")
    async def validation() -> dict[str, Any]:
        diagnostics = RegistryValidator().validate(resolved_catalog)
        return {
            "status": "valid" if not diagnostics else "invalid",
            "diagnostic_count": len(diagnostics),
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        }

    @app.get("/v1/admin/bid-check/notices")
    def bid_check_notices(page: int = 1, page_size: int = 50,
                          query: str | None = None, bid_status: str | None = None,
                          work_type: str | None = None, extraction_status: str | None = None,
                          review_status: str | None = None) -> dict[str, Any]:
        if resolved_bid_reader is None:
            raise HTTPException(status_code=503, detail={"code": "bid_check_database_unavailable"})
        return resolved_bid_reader.list_notices(
            page=max(1, page), page_size=max(1, min(page_size, 100)), query=query,
            bid_status=bid_status, work_type=work_type, extraction_status=extraction_status,
            review_status=review_status,
        )

    @app.get("/v1/admin/bid-check/notices/{bid_notice_id}/requirements")
    def bid_check_requirements(bid_notice_id: str) -> dict[str, Any]:
        if resolved_bid_reader is None:
            raise HTTPException(status_code=503, detail={"code": "bid_check_database_unavailable"})
        return {"requirements": resolved_bid_reader.get_requirements(bid_notice_id)}

    def runtime_contract_graph(runtime_contract_id: str) -> dict[str, Any]:
        if runtime_contract_id == "all":
            return build_runtime_contract_graph(
                resolved_catalog, list(resolved_catalog.runtime_contracts),
            )
        if runtime_contract_id not in resolved_catalog.runtime_contracts:
            raise HTTPException(
                status_code=404,
                detail={"code": "runtime_contract_not_found", "message": runtime_contract_id},
            )
        return build_runtime_contract_graph(resolved_catalog, [runtime_contract_id])

    @app.get("/v1/admin/runtime-contracts/{runtime_contract_id}/graph")
    async def get_runtime_contract_graph(runtime_contract_id: str) -> dict[str, Any]:
        return runtime_contract_graph(runtime_contract_id)

    return app


def app_factory() -> FastAPI:
    return create_admin_app()
