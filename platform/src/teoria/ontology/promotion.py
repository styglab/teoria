from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from teoria.ontology.authoring import OntologyAuthoringRepository


class IdentityProperty(BaseModel):
    code: str
    name: str
    value_type: str


class PromotionObject(BaseModel):
    code: str
    name: str
    legacy_ref: str
    description: str = ""
    identity_property: IdentityProperty


class PromotionOntology(BaseModel):
    namespace: str
    name: str
    description: str
    target_version: str
    based_on: str | None = None
    objects: list[PromotionObject] = Field(min_length=1)


class BusinessConceptPromotion(BaseModel):
    schema_version: str
    ontologies: list[PromotionOntology] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "BusinessConceptPromotion":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @property
    def legacy_refs(self) -> set[str]:
        return {item.legacy_ref for ontology in self.ontologies for item in ontology.objects}


def apply_business_concept_promotion(
    repository: OntologyAuthoringRepository,
    manifest: BusinessConceptPromotion,
    *,
    actor: str,
    publish: bool = False,
) -> dict[str, Any]:
    """Create authoring revisions from the reviewed promotion manifest.

    This intentionally uses the authoring lifecycle rather than schema migrations:
    business meaning is governed content, not database structure.
    """
    results: list[dict[str, Any]] = []
    for ontology in manifest.ontologies:
        versions = repository.list_versions(ontology.namespace)
        existing = next((x for x in versions if x["version"] == ontology.target_version), None)
        if existing:
            if not publish or existing["status"] == "published":
                results.append({"namespace": ontology.namespace, "version": ontology.target_version, "status": existing["status"], "action": "unchanged"})
                continue
            revision = existing
            if existing["status"] != "draft":
                raise ValueError(
                    f"Existing {ontology.namespace} {ontology.target_version} is {existing['status']}; "
                    "finish or revoke its lifecycle explicitly"
                )
        elif versions:
            revision = repository.create_draft(ontology.namespace, version=ontology.target_version, actor=actor)
        else:
            revision = repository.create_ontology(
                namespace=ontology.namespace,
                name=ontology.name,
                description=ontology.description,
                version=ontology.target_version,
                actor=actor,
            )
        version_id = UUID(revision["ontology_version_id"])
        if existing is None:
            created: dict[str, dict[str, Any]] = {}
            for item in ontology.objects:
                created[item.code] = repository.add_item(
                    version_id,
                    kind="object",
                    payload={
                        "code": item.code,
                        "name": item.name,
                        "description": item.description or f"{item.name} 업무 객체",
                        "stable_key": f"{ontology.namespace}.{item.code}",
                        "identity_policy": {"properties": [item.identity_property.code]},
                    },
                    actor=actor,
                )
            for item in ontology.objects:
                repository.add_item(
                    version_id,
                    kind="property",
                    payload={
                        "code": item.identity_property.code,
                        "name": item.identity_property.name,
                        "description": f"{item.name}을 식별하는 값",
                        "stable_key": f"{ontology.namespace}.{item.code}.{item.identity_property.code}",
                        "object_concept_id": created[item.code]["concept_id"],
                        "value_type": item.identity_property.value_type,
                        "cardinality": "one",
                    },
                    actor=actor,
                )
        validation = repository.validate(version_id)
        status = "draft"
        if publish:
            if validation["status"] != "valid":
                raise ValueError(f"Promotion validation failed for {ontology.namespace}: {validation['diagnostics']}")
            repository.transition(version_id, action="submit", actor=actor, comment="Reviewed migration manifest")
            repository.transition(version_id, action="approve", actor=actor, comment="Approved legacy concept promotion")
            repository.publish(version_id, actor=actor)
            status = "published"
        results.append({
            "namespace": ontology.namespace,
            "version": ontology.target_version,
            "status": status,
            "action": "created",
            "object_count": len(ontology.objects),
            "validation": validation,
        })
    return {"status": "complete", "ontologies": results}
