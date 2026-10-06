from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from teoria.ontology.blueprint import OntologyBlueprint
from teoria.ontology.extension import OntologyExtensionManifest
from teoria.ontology.migration import OntologyMigrationManifest


class ConceptTransition(BaseModel):
    action: Literal["map", "merge", "rename", "generalize"]
    targets: list[str] = Field(min_length=1)
    rationale: str


class OntologyUnificationManifest(BaseModel):
    schema_version: str
    target_namespace: str
    target_version: str
    concepts: dict[str, ConceptTransition]

    @classmethod
    def load(cls, path: Path) -> "OntologyUnificationManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def validate_unification_plan(
    migration: OntologyMigrationManifest,
    plan: OntologyUnificationManifest,
    blueprint: OntologyBlueprint,
    extensions: list[OntologyExtensionManifest],
) -> dict:
    legacy = {
        key for key, item in migration.objects.items()
        if item.classification == "BUSINESS_CONCEPT"
    }
    planned = set(plan.concepts)
    available = {item.stable_key for item in blueprint.objects}
    for extension in extensions:
        available.update(item.stable_key for item in extension.objects)
    missing_legacy = sorted(legacy - planned)
    unknown_legacy = sorted(planned - legacy)
    missing_targets = sorted({
        target for transition in plan.concepts.values()
        for target in transition.targets if target not in available
    })
    return {
        "status": "valid" if not missing_legacy and not unknown_legacy and not missing_targets else "invalid",
        "legacy_business_concept_count": len(legacy),
        "planned_concept_count": len(planned),
        "missing_legacy_concepts": missing_legacy,
        "unknown_legacy_concepts": unknown_legacy,
        "missing_target_concepts": missing_targets,
    }
