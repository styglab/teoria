from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from teoria.features.semantic_modeling.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog


def create_ontology_migration_router(
    resolved_catalog: RegistryCatalog,
    manifest_path: Path,
    application_database_url: str | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/admin/ontology-migration")
    async def ontology_migration() -> dict[str, Any]:
        if not manifest_path.exists():
            raise HTTPException(
                status_code=404,
                detail={"code": "ontology_migration_manifest_not_found"},
            )
        return await build_migration_report(
            resolved_catalog,
            OntologyMigrationManifest.load(manifest_path),
            application_database_url=application_database_url,
        )

    return router
