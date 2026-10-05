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
        for ontology_id, ontology in catalog.ontologies.items()
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
    stable_keys = _load_stable_keys(application_database_url) if application_database_url else set()
    missing_targets = sorted(
        ref.target_stable_key for ref in manifest.objects.values()
        if ref.target_stable_key and stable_keys and ref.target_stable_key not in stable_keys
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
        "capability_referenced_object_count": len(capability_usage),
        "mapping_referenced_object_count": len(mapping_usage),
        "objects": [
            {
                "legacy_ref": ref,
                **manifest.objects[ref].model_dump(),
                "capability_reference_count": capability_usage[ref],
                "mapping_reference_count": mapping_usage[ref],
            }
            for ref in sorted(manifest.objects)
        ],
    }


def _load_stable_keys(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        return {row[0] for row in connection.execute("SELECT stable_key FROM ontology.concepts WHERE retired_at IS NULL")}
