from __future__ import annotations

from typing import Any

from teoria.integrations.application_database.postgres import connect
from psycopg.rows import dict_row

from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog


class RuntimeBundleSnapshotRepository:
    """Export only published Ontology artifacts and currently approved Bindings."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def snapshot(
        self,
        *,
        ontology_namespaces: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        async with connect(self.database_url, row_factory=dict_row) as connection:
            rows = await (
                await connection.execute(
                    """
                SELECT o.namespace,v.version,a.artifact_id,a.schema_version,
                       a.checksum,a.content,a.created_at
                  FROM ontology.runtime_artifacts a
                  JOIN ontology.ontology_versions v USING (ontology_version_id)
                  JOIN ontology.ontologies o USING (ontology_id)
                 WHERE v.status='published'
                 ORDER BY o.namespace,v.version
                """
                )
            ).fetchall()
        ontologies = [_jsonable(dict(row)) for row in rows]
        if ontology_namespaces is not None:
            ontologies = [
                item for item in ontologies if item["namespace"] in ontology_namespaces
            ]
            missing = ontology_namespaces - {item["namespace"] for item in ontologies}
            if missing:
                raise ValueError(
                    f"published Ontology namespace not found: {', '.join(sorted(missing))}"
                )
        bindings = await BindingRepository(self.database_url).list_bindings(
            status="approved", limit=100_000
        )
        if ontology_namespaces is not None:
            bindings = [
                item
                for item in bindings
                if item["ontology_namespace"] in ontology_namespaces
            ]
        return ontologies, bindings


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def select_registry_bindings(
    catalog: RegistryCatalog, bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Omit targets retired from this release without changing authoring history.

    Retained targets still undergo the compiler's version and compatibility
    checks. In particular, this never rewrites an approved target's version.
    """
    return [
        item for item in bindings
        if (
            not str(item.get("target_type", "")).startswith("capability")
            or item.get("capability_id") in catalog.capabilities
        )
        and (
            item.get("target_type") != "api_field"
            or item.get("api_source_id") in catalog.sources
        )
    ]
