from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from teoria.ontology.authoring import OntologyAuthoringRepository


class PropertySpec(BaseModel):
    object: str
    code: str
    name: str
    value_type: str
    unit: str | None = None
    temporal: bool = False


class RelationshipSpec(BaseModel):
    code: str
    name: str
    source: str
    target: str


class OntologyEnrichmentSpec(BaseModel):
    namespace: str
    target_version: str
    properties: list[PropertySpec] = Field(default_factory=list)
    relationships: list[RelationshipSpec] = Field(default_factory=list)


class OntologyEnrichmentManifest(BaseModel):
    schema_version: str
    ontologies: list[OntologyEnrichmentSpec]

    @classmethod
    def load(cls, path: Path) -> "OntologyEnrichmentManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def apply_ontology_enrichment(repository: OntologyAuthoringRepository, manifest: OntologyEnrichmentManifest, *, actor: str, publish: bool) -> dict[str, Any]:
    results = []
    for spec in manifest.ontologies:
        versions = repository.list_versions(spec.namespace)
        existing = next((item for item in versions if item["version"] == spec.target_version), None)
        if existing:
            results.append({"namespace": spec.namespace, "version": spec.target_version, "status": existing["status"], "action": "unchanged"})
            continue
        revision = repository.create_draft(spec.namespace, version=spec.target_version, actor=actor)
        version_id = UUID(revision["ontology_version_id"])
        detail = repository.get_version(version_id)
        objects = {item["code"]: item for item in detail["objects"]}
        for prop in spec.properties:
            owner = objects.get(prop.object)
            if owner is None:
                raise ValueError(f"Unknown object {spec.namespace}.{prop.object}")
            repository.add_item(version_id, kind="property", payload={
                "code": prop.code, "name": prop.name,
                "stable_key": f"{spec.namespace}.{prop.object}.{prop.code}",
                "object_concept_id": owner["concept_id"], "value_type": prop.value_type,
                "cardinality": "optional", "unit": prop.unit, "temporal": prop.temporal,
            }, actor=actor)
        for rel in spec.relationships:
            source, target = objects.get(rel.source), objects.get(rel.target)
            if source is None or target is None:
                raise ValueError(f"Unknown relationship endpoint {spec.namespace}.{rel.code}")
            repository.add_item(version_id, kind="relationship", payload={
                "code": rel.code, "name": rel.name,
                "stable_key": f"{spec.namespace}.{rel.code}",
                "source_object_concept_id": source["concept_id"],
                "target_object_concept_id": target["concept_id"],
                "source_cardinality": "one", "target_cardinality": "many", "temporal": True,
            }, actor=actor)
        validation = repository.validate(version_id)
        if publish:
            if validation["status"] != "valid":
                raise ValueError(f"Enrichment validation failed: {validation['diagnostics']}")
            repository.transition(version_id, action="submit", actor=actor, comment="Reviewed ontology enrichment manifest")
            repository.transition(version_id, action="approve", actor=actor, comment="Approved ontology enrichment")
            repository.publish(version_id, actor=actor)
        results.append({"namespace": spec.namespace, "version": spec.target_version, "status": "published" if publish else "draft", "action": "created", "validation": validation})
    return {"status": "complete", "ontologies": results}
