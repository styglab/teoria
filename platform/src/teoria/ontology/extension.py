from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.ontology.blueprint import BlueprintObject, BlueprintRelationship


class OntologyExtensionManifest(BaseModel):
    schema_version: str
    ontology_namespace: str
    ontology_version: str
    objects: list[BlueprintObject] = Field(default_factory=list)
    relationships: list[BlueprintRelationship] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "OntologyExtensionManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def apply_ontology_extension(
    repository: OntologyAuthoringRepository,
    manifest: OntologyExtensionManifest,
    *,
    actor: str,
) -> dict[str, Any]:
    version = next(
        (item for item in repository.list_versions(manifest.ontology_namespace)
         if item["version"] == manifest.ontology_version), None,
    )
    if version is None or version["status"] != "draft":
        raise ValueError("Ontology extensions can only be applied to the requested draft")
    version_id = UUID(version["ontology_version_id"])
    detail = repository.get_version(version_id)
    objects = {item["code"]: item for item in detail["objects"]}
    created_objects = 0
    for item in manifest.objects:
        if item.code in objects:
            continue
        created = repository.add_item(version_id, kind="object", payload={
            "code": item.code, "name": item.name, "description": item.description,
            "stable_key": item.stable_key,
            "identity_policy": {"properties": item.identity_properties},
        }, actor=actor)
        for prop in item.properties:
            repository.add_item(version_id, kind="property", payload={
                **prop.model_dump(), "object_concept_id": created["concept_id"],
            }, actor=actor)
        objects[item.code] = created
        created_objects += 1
    existing_relationships = {item["code"] for item in detail["relationships"]}
    created_relationships = 0
    for item in manifest.relationships:
        if item.code in existing_relationships:
            continue
        source, target = objects.get(item.source), objects.get(item.target)
        if source is None or target is None:
            raise ValueError(f"Unknown extension relationship endpoint: {item.code}")
        repository.add_item(version_id, kind="relationship", payload={
            **item.model_dump(exclude={"source", "target"}),
            "source_object_concept_id": source["concept_id"],
            "target_object_concept_id": target["concept_id"],
        }, actor=actor)
        created_relationships += 1
    return {
        "status": "complete", "created_objects": created_objects,
        "created_relationships": created_relationships,
        "validation": repository.validate(version_id),
    }
