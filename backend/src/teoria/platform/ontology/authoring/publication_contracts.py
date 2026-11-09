"""Source-independent, immutable publication contracts; no authoring DB or I/O.

Data pipelines, expression dictionaries and Runtime consumers share these checks.
The caller must establish publication authority through the owning service or a
verified Runtime bundle; a valid checksum alone is not evidence of approval.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teoria.platform.ontology.authoring.models import OntologyPublicationRef

__all__ = ['OntologyPublicationRef', 'PublishedConceptRef', 'PublishedOntology', 'PublishedOntologyContext',
           'publication_checksum', 'publication_concepts', 'select_publication_concepts']


def publication_checksum(content: Any) -> str:
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class PublishedConceptRef(BaseModel):
    """Meaning identity, separate from the ID of an observed subject or value."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    ontology: OntologyPublicationRef
    concept_id: UUID


class PublishedOntology(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    ontology: OntologyPublicationRef
    content: dict[str, Any]

    @model_validator(mode="after")
    def verify_content(self):
        if (self.content.get("namespace"), self.content.get("version")) != (
            self.ontology.namespace, self.ontology.version
        ):
            raise ValueError("ontology_publication_identity_mismatch")
        if publication_checksum(self.content) != self.ontology.checksum:
            raise ValueError("ontology_publication_checksum_mismatch")
        return self


class PublishedOntologyContext(BaseModel):
    """Pinned definitions without a dependency on a source or expression dictionary."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    schema_version: Literal[1] = 1
    artifact_kind: Literal["published_ontology_context"] = "published_ontology_context"
    ontologies: list[PublishedOntology] = Field(min_length=1)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verify_context(self):
        refs = [item.ontology.version_id for item in self.ontologies]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_ontology_publication")
        body = [item.model_dump(mode="json") for item in self.ontologies]
        if publication_checksum(body) != self.checksum:
            raise ValueError("ontology_context_checksum_mismatch")
        return self

    @classmethod
    def from_publications(cls, publications):
        items = [PublishedOntology.model_validate(item) for item in publications]
        items.sort(key=lambda item: str(item.ontology.version_id))
        return cls(ontologies=items, checksum=publication_checksum(
            [item.model_dump(mode="json") for item in items]))


def publication_concepts(publications: Iterable[PublishedOntology | dict]) -> dict[str, dict]:
    """Project Stable Concept IDs; translate revision endpoints only inside this owner."""
    catalog = {}
    for value in publications:
        publication = PublishedOntology.model_validate(value)
        reference = publication.ontology.model_dump(mode="json")
        content = publication.content
        objects = {str(obj["business_object_id"]): str(obj["concept_id"])
                   for obj in content["objects"]}
        rows = []
        for obj in content["objects"]:
            rows.append({**obj, "kind": "object", "owner_concept_id": None})
            rows.extend({**prop, "kind": "property", "owner_concept_id": str(obj["concept_id"])}
                        for prop in obj["properties"])
        for relation in content["relationships"]:
            if any(str(relation[key]) not in objects for key in ("source_object_id", "target_object_id")):
                raise ValueError("ontology_context_endpoint_missing")
            rows.append({**relation, "kind": "relationship", "owner_concept_id": None,
                         "source_concept_id": objects[str(relation["source_object_id"])],
                         "target_concept_id": objects[str(relation["target_object_id"])]})
        for row in rows:
            identifier = str(row["concept_id"])
            if identifier in catalog:
                raise ValueError("ambiguous_ontology_context_concept")
            catalog[identifier] = {
                "concept_id": identifier, "stable_key": row["stable_key"], "name": row["name"],
                "definition": row.get("description", ""), "kind": row["kind"], "ontology": reference,
                **{key: row.get(key) for key in ("owner_concept_id", "source_concept_id",
                    "target_concept_id", "value_type", "cardinality", "unit", "quantity_dimension")},
                "allowed_units": row.get("allowed_units", []),
            }
    return catalog


def select_publication_concepts(publications, concept_ids):
    catalog = publication_concepts(publications)
    selected = {str(identifier) for identifier in concept_ids}
    if not selected <= catalog.keys():
        raise ValueError("ontology_context_concept_not_published")
    pending = list(selected)
    while pending:
        concept = catalog[pending.pop()]
        for field in ("owner_concept_id", "source_concept_id", "target_concept_id"):
            identifier = concept.get(field)
            if identifier and identifier not in selected:
                if identifier not in catalog:
                    raise ValueError("ontology_context_endpoint_missing")
                selected.add(identifier)
                pending.append(identifier)
    return {identifier: catalog[identifier] for identifier in sorted(selected)}
