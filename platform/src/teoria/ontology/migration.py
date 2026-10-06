from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

import psycopg
import yaml
from pydantic import BaseModel, Field

from teoria.registry.loader import RegistryCatalog


class LegacyObjectDisposition(BaseModel):
    classification: Literal["BUSINESS_CONCEPT", "RUNTIME_PROJECTION", "ASSESSMENT_RESULT", "DEPRECATED"]
    migration_status: Literal["mapped", "planned", "runtime_contract", "retain", "deprecated"]
    rationale: str
    target_stable_key: str | None = None


class OntologyMigrationManifest(BaseModel):
    schema_version: str
    source_registry_release: str
    target_ontology: str
    classifications: dict[str, str]
    objects: dict[str, LegacyObjectDisposition]

    @classmethod
    def load(cls, path: Path) -> "OntologyMigrationManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def build_migration_report(
    catalog: RegistryCatalog,
    manifest: OntologyMigrationManifest,
    *,
    application_database_url: str | None = None,
) -> dict:
    registry_objects = {
        f"{ontology_id}.{item.id}"
        for ontology_id, ontology in catalog.runtime_contracts.items()
        for item in ontology.object_types
    }
    manifest_objects = set(manifest.objects)
    missing = sorted(registry_objects - manifest_objects)
    unknown = sorted(manifest_objects - registry_objects)
    capability_usage: Counter[str] = Counter()
    for capability in catalog.capabilities.values():
        for returned in capability.returns:
            parts = returned.split(".")
            if len(parts) >= 2:
                candidate = ".".join(parts[:2])
                if candidate in registry_objects:
                    capability_usage[candidate] += 1
    mapping_usage: Counter[str] = Counter()
    for mapping in catalog.mappings.values():
        for object_ref in mapping.bindings:
            qualified = object_ref if object_ref.startswith(f"{mapping.ontology}.") else f"{mapping.ontology}.{object_ref}"
            candidate = ".".join(qualified.split(".")[:2])
            if candidate in registry_objects:
                mapping_usage[candidate] += 1
    published_concepts = (
        _load_published_concepts(application_database_url)
        if application_database_url else {}
    )
    stable_keys = set(published_concepts)
    missing_targets = sorted(
        ref.target_stable_key for ref in manifest.objects.values()
        if ref.target_stable_key
        and application_database_url is not None
        and ref.target_stable_key not in stable_keys
    )
    classifications = Counter(item.classification for item in manifest.objects.values())
    statuses = Counter(item.migration_status for item in manifest.objects.values())
    return {
        "status": "valid" if not missing and not unknown and not missing_targets else "invalid",
        "source_registry_release": manifest.source_registry_release,
        "registry_object_count": len(registry_objects),
        "manifest_object_count": len(manifest_objects),
        "classification_counts": dict(sorted(classifications.items())),
        "migration_status_counts": dict(sorted(statuses.items())),
        "missing_objects": missing,
        "unknown_objects": unknown,
        "missing_target_stable_keys": missing_targets,
        "authority_boundary": {
            "business_ontology": "application_database_published_artifact",
            "runtime_contract": "immutable_registry_release",
            "runtime_mapping": "registry_mapping",
            "semantic_connection": "ontology_binding",
        },
        "published_target_verification": (
            "verified" if application_database_url is not None else "not_checked"
        ),
        "published_target_count": sum(
            1 for item in manifest.objects.values()
            if item.target_stable_key in published_concepts
        ),
        "capability_referenced_object_count": len(capability_usage),
        "mapping_referenced_object_count": len(mapping_usage),
        "objects": [
            {
                "legacy_ref": ref,
                **manifest.objects[ref].model_dump(),
                "capability_reference_count": capability_usage[ref],
                "mapping_reference_count": mapping_usage[ref],
                "published_target": (
                    published_concepts.get(manifest.objects[ref].target_stable_key)
                    if manifest.objects[ref].target_stable_key else None
                ),
                "runtime_contract_required": bool(
                    capability_usage[ref] or mapping_usage[ref]
                ),
                "transition_status": (
                    "semantically_linked"
                    if manifest.objects[ref].target_stable_key in published_concepts
                    else "runtime_only"
                    if manifest.objects[ref].classification != "BUSINESS_CONCEPT"
                    else "target_not_verified"
                ),
            }
            for ref in sorted(manifest.objects)
        ],
    }


def _load_published_concepts(database_url: str) -> dict[str, dict[str, str]]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            WITH published_members AS (
                SELECT bo.concept_id,bo.ontology_version_id
                  FROM ontology.business_objects bo
                UNION ALL
                SELECT p.concept_id,bo.ontology_version_id
                  FROM ontology.object_properties p
                  JOIN ontology.business_objects bo USING (business_object_id)
                UNION ALL
                SELECT concept_id,ontology_version_id FROM ontology.relationship_types
                UNION ALL
                SELECT concept_id,ontology_version_id FROM ontology.business_rules
                UNION ALL
                SELECT concept_id,ontology_version_id FROM ontology.metrics
            )
            SELECT c.stable_key,v.version,a.artifact_id,a.checksum
              FROM published_members pm
              JOIN ontology.concepts c USING (concept_id)
              JOIN ontology.ontology_versions v USING (ontology_version_id)
              JOIN ontology.runtime_artifacts a USING (ontology_version_id)
             WHERE v.status='published' AND c.retired_at IS NULL
            """
        ).fetchall()
    return {
        row[0]: {
            "ontology_version": row[1],
            "artifact_id": str(row[2]),
            "artifact_checksum": row[3],
        }
        for row in rows
    }
