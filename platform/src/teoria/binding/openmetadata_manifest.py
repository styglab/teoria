from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import psycopg
import yaml
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from teoria.binding.repository import BindingRepository


class PlannedOpenMetadataBinding(BaseModel):
    ontology_stable_key: str
    target_type: Literal["glossary_term", "data_asset"]
    entity_type: str
    fully_qualified_name: str
    binding_type: str
    purpose: str | None = None
    authority: Literal["authoritative", "preferred", "supplemental"]
    priority: int = 100
    note: str | None = None


class OpenMetadataBindingManifest(BaseModel):
    schema_version: str
    ontology_namespace: str
    ontology_version: str
    status: str
    bindings: list[PlannedOpenMetadataBinding] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "OpenMetadataBindingManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def apply_openmetadata_binding_manifest(
    repository: BindingRepository,
    manifest: OpenMetadataBindingManifest,
    *,
    actor: str,
) -> dict[str, Any]:
    created = 0
    unchanged = 0
    with psycopg.connect(repository.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """SELECT c.stable_key,p.property_id,c.concept_id
                 FROM ontology.object_properties p
                 JOIN ontology.business_objects bo USING (business_object_id)
                 JOIN ontology.ontology_versions v USING (ontology_version_id)
                 JOIN ontology.ontologies o USING (ontology_id)
                 JOIN ontology.concepts c ON c.concept_id=p.concept_id
                WHERE o.namespace=%s AND v.version=%s AND v.status='draft'""",
            (manifest.ontology_namespace, manifest.ontology_version),
        ).fetchall()
    properties = {row["stable_key"]: row for row in rows}
    for item in manifest.bindings:
        prop = properties.get(item.ontology_stable_key)
        if prop is None:
            raise ValueError(f"Unknown draft ontology property: {item.ontology_stable_key}")
        locator = f"openmetadata://{item.entity_type}/{item.fully_qualified_name}"
        if repository.get_active_binding(
            ontology_concept_id=prop["concept_id"],
            target_type=item.target_type,
            target_locator=locator,
        ):
            unchanged += 1
            continue
        repository.create_openmetadata_binding(
            ontology_ref_type="property",
            ontology_ref_id=prop["property_id"],
            ontology_concept_id=None,
            target_type=item.target_type,
            external_entity_id=item.fully_qualified_name,
            entity_type=item.entity_type,
            fully_qualified_name=item.fully_qualified_name,
            external_version=None,
            binding_type=item.binding_type,
            purpose=item.purpose,
            authority=item.authority,
            priority=item.priority,
            confidence=1.0,
            provenance={"source": "reviewed_manifest", "note": item.note},
            created_by=actor,
        )
        created += 1
    return {"status": "complete", "created": created, "unchanged": unchanged}
