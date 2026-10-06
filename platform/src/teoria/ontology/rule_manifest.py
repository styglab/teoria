from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from teoria.ontology.authoring import OntologyAuthoringRepository


class RuleSpec(BaseModel):
    code: str
    name: str
    stable_key: str
    subject: str
    description: str
    evaluator_key: str
    expression: dict[str, Any]
    expression_language: str = "teoria_expression_v1"
    rule_version: str = "1.0"


class BusinessRuleManifest(BaseModel):
    schema_version: str
    ontology_namespace: str
    ontology_version: str
    rules: list[RuleSpec] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "BusinessRuleManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def apply_business_rule_manifest(
    repository: OntologyAuthoringRepository,
    manifest: BusinessRuleManifest,
    *,
    actor: str,
) -> dict[str, Any]:
    version = next(
        (item for item in repository.list_versions(manifest.ontology_namespace)
         if item["version"] == manifest.ontology_version),
        None,
    )
    if version is None or version["status"] != "draft":
        raise ValueError("Business rules can only be applied to the requested draft version")
    version_id = UUID(version["ontology_version_id"])
    detail = repository.get_version(version_id)
    objects = {item["code"]: item for item in detail["objects"]}
    existing = {item["code"] for item in detail["rules"]}
    created = 0
    for rule in manifest.rules:
        if rule.code in existing:
            continue
        subject = objects.get(rule.subject)
        if subject is None:
            raise ValueError(f"Unknown rule subject: {rule.subject}")
        repository.add_item(
            version_id,
            kind="rule",
            payload={
                **rule.model_dump(exclude={"subject"}),
                "subject_object_concept_id": subject["concept_id"],
            },
            actor=actor,
        )
        created += 1
    return {
        "status": "complete",
        "created": created,
        "unchanged": len(manifest.rules) - created,
        "validation": repository.validate(version_id),
    }
