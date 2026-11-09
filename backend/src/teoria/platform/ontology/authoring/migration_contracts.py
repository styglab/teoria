"""Classification manifest for the historical Ontology migration."""

from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field


class LegacyObjectDisposition(BaseModel):
    classification: Literal[
        "BUSINESS_CONCEPT", "RUNTIME_PROJECTION", "ASSESSMENT_RESULT", "DEPRECATED"
    ]
    migration_status: Literal[
        "mapped", "planned", "runtime_contract", "retain", "deprecated"
    ]
    rationale: str
    target_stable_key: str | None = None


class OntologyMigrationManifest(BaseModel):
    schema_version: str
    source_registry_release: str
    target_ontology: str
    classifications: dict[str, str]
    objects: dict[str, LegacyObjectDisposition]
    draft_objects: dict[str, LegacyObjectDisposition] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "OntologyMigrationManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
