from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from teoria.binding.repository import BindingRepository


class RuntimeBundleSnapshotRepository:
    """Export only published Ontology artifacts and currently approved Bindings."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT o.namespace,v.version,a.artifact_id,a.schema_version,
                       a.checksum,a.content,a.created_at
                  FROM ontology.runtime_artifacts a
                  JOIN ontology.ontology_versions v USING (ontology_version_id)
                  JOIN ontology.ontologies o USING (ontology_id)
                 WHERE v.status='published'
                 ORDER BY o.namespace,v.version
                """
            ).fetchall()
        ontologies = [_jsonable(dict(row)) for row in rows]
        bindings = BindingRepository(self.database_url).list_bindings(
            status="approved", limit=100_000
        )
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
