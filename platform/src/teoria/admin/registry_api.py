from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from teoria.admin.ontology_graph import build_runtime_contract_graph
from teoria.admin.overview import build_registry_overview
from teoria.registry.composition import create_registry_validator
from teoria.registry.loader import RegistryCatalog


def create_registry_router(resolved_catalog: RegistryCatalog) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/admin/overview")
    async def overview() -> dict[str, Any]:
        return build_registry_overview(resolved_catalog)


    @router.get("/v1/admin/registry-release")
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


    @router.get("/v1/admin/runtime-contracts")
    async def list_runtime_contracts() -> dict[str, list[dict[str, Any]]]:
        return {"runtime_contracts": runtime_contract_summaries()}


    @router.get("/v1/admin/capabilities")
    async def list_capabilities() -> dict[str, list[dict[str, Any]]]:
        return {
            "capabilities": [
                {
                    "id": capability.id,
                    "name": capability.name or capability.id,
                    "description": capability.description,
                    "kind": capability.kind,
                    "exposure": capability.exposure,
                    "processor": capability.processor,
                    "effects": capability.effects.model_dump(),
                    "inputs": list(capability.inputs),
                    "steps": [step.call for step in capability.steps],
                    "returns": capability.returns,
                }
                for capability in resolved_catalog.capabilities.values()
            ]
        }


    @router.get("/v1/admin/sources")
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


    @router.get("/v1/admin/mappings")
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


    @router.get("/v1/admin/lineage")
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


    @router.get("/v1/admin/validation")
    async def validation() -> dict[str, Any]:
        diagnostics = create_registry_validator().validate(resolved_catalog)
        return {
            "status": "valid" if not diagnostics else "invalid",
            "diagnostic_count": len(diagnostics),
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        }


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


    @router.get("/v1/admin/runtime-contracts/{runtime_contract_id}/graph")
    async def get_runtime_contract_graph(runtime_contract_id: str) -> dict[str, Any]:
        return runtime_contract_graph(runtime_contract_id)


    return router
