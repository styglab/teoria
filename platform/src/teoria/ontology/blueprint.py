from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, Field, model_validator

from teoria.ontology.authoring import OntologyAuthoringRepository


class BlueprintProperty(BaseModel):
    code: str
    name: str
    value_type: str
    stable_key: str
    description: str = ""
    cardinality: str = "optional"
    unit: str | None = None
    temporal: bool = False


class BlueprintObject(BaseModel):
    code: str
    name: str
    stable_key: str
    description: str
    identity_properties: list[str] = Field(default_factory=list)
    properties: list[BlueprintProperty] = Field(min_length=1)

    @model_validator(mode="after")
    def identity_properties_exist(self) -> "BlueprintObject":
        property_codes = {item.code for item in self.properties}
        missing = set(self.identity_properties) - property_codes
        if missing:
            raise ValueError(f"Unknown identity properties for {self.code}: {sorted(missing)}")
        return self


class BlueprintRelationship(BaseModel):
    code: str
    name: str
    stable_key: str
    source: str
    target: str
    source_cardinality: str = "many"
    target_cardinality: str = "many"
    temporal: bool = False
    transitive: bool = False


class OntologyBlueprint(BaseModel):
    schema_version: str
    namespace: str
    name: str
    description: str
    target_version: str
    objects: list[BlueprintObject] = Field(min_length=1)
    relationships: list[BlueprintRelationship] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "OntologyBlueprint":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @model_validator(mode="after")
    def references_are_unambiguous(self) -> "OntologyBlueprint":
        codes = [item.code for item in self.objects]
        stable_keys = [item.stable_key for item in self.objects]
        if len(codes) != len(set(codes)) or len(stable_keys) != len(set(stable_keys)):
            raise ValueError("Blueprint object codes and stable keys must be unique")
        known = set(codes)
        for relationship in self.relationships:
            if relationship.source not in known or relationship.target not in known:
                raise ValueError(f"Unknown relationship endpoint: {relationship.code}")
        return self


def apply_ontology_blueprint(
    repository: OntologyAuthoringRepository,
    blueprint: OntologyBlueprint,
    *,
    actor: str,
) -> dict[str, Any]:
    """Create a reviewed ontology blueprint as a draft; never publish implicitly."""
    versions = repository.list_versions(blueprint.namespace)
    existing = next((item for item in versions if item["version"] == blueprint.target_version), None)
    if existing:
        return {
            "namespace": blueprint.namespace,
            "version": blueprint.target_version,
            "status": existing["status"],
            "action": "unchanged",
            "ontology_version_id": existing["ontology_version_id"],
        }
    if versions:
        raise ValueError(
            f"Blueprint bootstrap cannot add a new version to existing ontology: {blueprint.namespace}"
        )
    revision = repository.create_ontology(
        namespace=blueprint.namespace,
        name=blueprint.name,
        description=blueprint.description,
        version=blueprint.target_version,
        actor=actor,
    )
    version_id = UUID(revision["ontology_version_id"])
    object_concepts: dict[str, str] = {}
    for item in blueprint.objects:
        created = repository.add_item(
            version_id,
            kind="object",
            payload={
                "code": item.code,
                "name": item.name,
                "description": item.description,
                "stable_key": item.stable_key,
                "identity_policy": {"properties": item.identity_properties},
            },
            actor=actor,
        )
        object_concepts[item.code] = created["concept_id"]
        for prop in item.properties:
            repository.add_item(
                version_id,
                kind="property",
                payload={
                    **prop.model_dump(),
                    "object_concept_id": created["concept_id"],
                },
                actor=actor,
            )
    for relationship in blueprint.relationships:
        repository.add_item(
            version_id,
            kind="relationship",
            payload={
                **relationship.model_dump(exclude={"source", "target"}),
                "source_object_concept_id": object_concepts[relationship.source],
                "target_object_concept_id": object_concepts[relationship.target],
            },
            actor=actor,
        )
    return {
        "namespace": blueprint.namespace,
        "version": blueprint.target_version,
        "status": "draft",
        "action": "created",
        "ontology_version_id": str(version_id),
        "validation": repository.validate(version_id),
    }
