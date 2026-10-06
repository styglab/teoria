from __future__ import annotations

import hashlib
import json
from typing import Any
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from teoria.registry.artifact import (
    LoadedRuntimeBundle,
    RegistryArtifactStore,
    RuntimeBundleLoader,
)


class BundleContextRepository:
    """Resolve governed context exclusively from one immutable Runtime bundle."""

    def __init__(self, bundle: LoadedRuntimeBundle) -> None:
        self.bundle = bundle

    @classmethod
    def from_path(cls, path: Path | str) -> "BundleContextRepository":
        return cls(RuntimeBundleLoader(path).load())

    @classmethod
    def from_store(cls, path: Path | str) -> "BundleContextRepository":
        return cls(RegistryArtifactStore(path).load_active())

    def resolve_property(self, term: str) -> dict[str, Any] | None:
        normalized = term.casefold()
        candidates: list[tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for artifact in self.bundle.ontologies:
            content = artifact["content"]
            for owner in content.get("objects", []):
                for prop in owner.get("properties", []):
                    stable_key = str(prop.get("stable_key") or "")
                    score = (
                        0 if stable_key == term else
                        1 if str(prop.get("name") or "").casefold() == normalized else
                        2 if str(prop.get("code") or "").casefold() == normalized else
                        3
                    )
                    if score < 3:
                        candidates.append((score, artifact, owner, prop))
        if not candidates:
            return None
        _, artifact, owner, prop = min(
            candidates, key=lambda item: (item[0], str(item[3].get("stable_key")))
        )
        property_bindings = self._bindings(str(prop["stable_key"]))
        object_bindings = [
            item for item in self._bindings(str(owner["stable_key"]))
            if str(item.get("target_type") or "").startswith("capability")
        ]
        return {
            "stable_key": prop["stable_key"],
            "name": prop.get("name"),
            "description": prop.get("description"),
            "value_type": prop.get("value_type"),
            "unit": prop.get("unit"),
            "namespace": artifact["namespace"],
            "object_code": owner.get("code"),
            "object_name": owner.get("name"),
            "ontology_version": artifact["version"],
            "artifact_id": artifact.get("artifact_id"),
            "schema_version": artifact.get("schema_version"),
            "checksum": artifact["checksum"],
            "bindings": property_bindings,
            "object_capabilities": object_bindings,
        }

    def _bindings(self, stable_key: str) -> list[dict[str, Any]]:
        return [
            _runtime_binding(item)
            for item in self.bundle.bindings
            if item.get("ontology_stable_key") == stable_key
        ]


class ContextRepository:
    """Read-only boundary over published ontology artifacts and approved bindings."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def resolve_property(self, term: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT c.concept_id,c.stable_key,p.name,p.description,p.value_type,
                       p.unit,owner.concept_id AS object_concept_id,
                       owner.code AS object_code,owner.name AS object_name,
                       o.namespace,v.version AS ontology_version,
                       a.artifact_id,a.schema_version,a.checksum,a.content,a.created_at
                  FROM ontology.object_properties p
                  JOIN ontology.business_objects owner ON owner.business_object_id=p.business_object_id
                  JOIN ontology.ontology_versions v ON v.ontology_version_id=owner.ontology_version_id
                  JOIN ontology.ontologies o ON o.ontology_id=v.ontology_id
                  JOIN ontology.concepts c ON c.concept_id=p.concept_id
                  JOIN ontology.runtime_artifacts a ON a.ontology_version_id=v.ontology_version_id
                 WHERE v.status='published'
                   AND (c.stable_key=%s OR lower(p.name)=lower(%s) OR lower(p.code)=lower(%s))
                 ORDER BY CASE WHEN c.stable_key=%s THEN 0 WHEN lower(p.name)=lower(%s) THEN 1 ELSE 2 END
                 LIMIT 1
                """,
                (term, term, term, term, term),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            self._verify_artifact(result["content"], result["checksum"])
            result["bindings"] = self._bindings(connection, result["concept_id"])
            result["object_capabilities"] = [
                item for item in self._bindings(connection, result["object_concept_id"])
                if item["target_type"].startswith("capability")
            ]
        return _jsonable(result)

    @staticmethod
    def _bindings(connection, concept_id) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT ob.binding_id,ob.target_type,ob.target_locator,ob.target_version,
                   ob.binding_type,ob.purpose,ob.authority,ob.priority,ob.confidence,
                   ob.provenance,mt.external_entity_id,mt.entity_type,
                   mt.fully_qualified_name,mt.external_version,mt.last_verified_at,
                   ct.capability_id,ct.target_scope,ct.field_path,
                   ct.contract_version,ct.registry_version,ct.last_verified_at AS capability_verified_at,
                   at.source_id AS api_source_id,at.operation_id AS api_operation_id,
                   at.object_id AS api_object_id,at.field_path AS api_field_path,
                   at.contract_version AS api_contract_version,
                   at.registry_version AS api_registry_version,
                   at.last_verified_at AS api_verified_at
              FROM binding.ontology_bindings ob
         LEFT JOIN binding.metadata_targets mt ON mt.metadata_target_id=ob.metadata_target_id
         LEFT JOIN binding.capability_targets ct ON ct.capability_target_id=ob.capability_target_id
         LEFT JOIN binding.api_field_targets at ON at.api_field_target_id=ob.api_field_target_id
             WHERE ob.ontology_concept_id=%s AND ob.status='approved'
               AND (ob.valid_from IS NULL OR ob.valid_from <= current_date)
               AND (ob.valid_to IS NULL OR ob.valid_to >= current_date)
             ORDER BY ob.priority,ob.target_type,ob.target_locator
            """,
            (concept_id,),
        ).fetchall()
        return [dict(item) for item in rows]

    @staticmethod
    def _verify_artifact(content: dict[str, Any], checksum: str) -> None:
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        actual = hashlib.sha256(encoded.encode()).hexdigest()
        if actual != checksum:
            raise ValueError("published ontology artifact checksum mismatch")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "content"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def _runtime_binding(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    result.update({
        "target_scope": item.get("capability_target_scope"),
        "field_path": item.get("capability_field_path"),
        "contract_version": item.get("capability_contract_version"),
        "registry_version": item.get("capability_registry_version"),
        "last_verified_at": (
            item.get("last_verified_at")
            or item.get("capability_last_verified_at")
            or item.get("api_last_verified_at")
        ),
    })
    return result
