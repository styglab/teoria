from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from teoria.admin.ontology_graph import build_ontology_graph
from teoria.admin.overview import build_registry_overview
from teoria.admin.bid_check import BidCheckReader
from teoria.config import Settings, bootstrap_settings
from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.validator import RegistryValidator


def create_admin_app(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    bid_check_reader: BidCheckReader | None = None,
) -> FastAPI:
    resolved_settings = settings or bootstrap_settings()
    resolved_catalog = catalog or RegistryLoader(resolved_settings.registry_path).load()
    resolved_bid_reader = bid_check_reader or (
        BidCheckReader(resolved_settings.admin_data_database_url)
        if resolved_settings.admin_data_database_url else None
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
            allow_methods=["GET"],
            allow_headers=["*"],
        )

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

    @app.get("/v1/admin/ontologies")
    async def list_ontologies() -> dict[str, list[dict[str, Any]]]:
        return {
            "ontologies": [
                {
                    "id": ontology.id,
                    "name": ontology.name,
                    "description": ontology.description,
                    "object_count": len(ontology.object_types),
                    "link_count": len(ontology.link_types),
                }
                for ontology in resolved_catalog.ontologies.values()
            ]
        }

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

    @app.get("/v1/admin/ontologies/{ontology_id}/graph")
    async def ontology_graph(ontology_id: str) -> dict[str, Any]:
        if ontology_id == "all":
            return build_ontology_graph(resolved_catalog, list(resolved_catalog.ontologies))
        if ontology_id not in resolved_catalog.ontologies:
            raise HTTPException(status_code=404, detail={"code": "ontology_not_found", "message": ontology_id})
        return build_ontology_graph(resolved_catalog, [ontology_id])

    return app


def app_factory() -> FastAPI:
    return create_admin_app()
