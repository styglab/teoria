from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from teoria.binding.repository import BindingRepository
from teoria.registry.loader import RegistryCatalog


class CapabilityBindingSeed(BaseModel):
    ontology_namespace: str | None = None
    ontology_stable_key: str
    capability_id: str
    target_scope: Literal["capability", "input", "output"]
    field_path: str | None = None
    binding_type: str
    purpose: str = "runtime_semantic_resolution"
    authority: Literal["authoritative", "preferred", "supplemental"] = "preferred"
    priority: int = Field(default=100, ge=0)


class CapabilityBindingManifest(BaseModel):
    schema_version: str
    bindings: list[CapabilityBindingSeed] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "CapabilityBindingManifest":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def validate_catalog(self, catalog: RegistryCatalog) -> list[str]:
        diagnostics: list[str] = []
        for item in self.bindings:
            capability = catalog.capabilities.get(item.capability_id)
            if capability is None:
                diagnostics.append(f"unknown capability: {item.capability_id}")
            elif item.target_scope == "input" and item.field_path not in capability.inputs:
                diagnostics.append(f"unknown input: {item.capability_id}.{item.field_path}")
            elif item.target_scope == "output" and item.field_path not in capability.returns:
                diagnostics.append(f"unknown output: {item.capability_id}.{item.field_path}")
        return diagnostics


def apply_capability_binding_manifest(
    repository: BindingRepository,
    catalog: RegistryCatalog,
    manifest: CapabilityBindingManifest,
    *,
    actor: str,
    approve: bool,
) -> dict:
    diagnostics = manifest.validate_catalog(catalog)
    if diagnostics:
        raise ValueError("; ".join(diagnostics))
    registry_version = catalog.release.version if catalog.release else "draft"
    created = []
    unchanged = []
    for item in manifest.bindings:
        concept = repository.get_published_concept(
            item.ontology_stable_key,
            ontology_namespace=item.ontology_namespace,
        )
        if concept is None:
            raise ValueError(f"Unknown published ontology concept: {item.ontology_stable_key}")
        target_type = {
            "capability": "capability",
            "input": "capability_input",
            "output": "capability_output",
        }[item.target_scope]
        locator = f"capability://{item.capability_id}"
        if item.field_path:
            locator = f"{locator}/{item.target_scope}/{item.field_path}"
        existing = repository.get_active_binding(
            ontology_concept_id=concept["concept_id"],
            target_type=target_type,
            target_locator=locator,
        )
        if existing:
            unchanged.append(existing)
            continue
        binding = repository.create_capability_binding(
            ontology_ref_type=concept["concept_kind"],
            ontology_ref_id=None,
            ontology_concept_id=concept["concept_id"],
            capability_id=item.capability_id,
            target_scope=item.target_scope,
            field_path=item.field_path,
            contract_version=registry_version,
            registry_version=registry_version,
            binding_type=item.binding_type,
            purpose=item.purpose,
            authority=item.authority,
            priority=item.priority,
            confidence=1.0,
            provenance={"source": "reviewed_manifest", "manifest_version": manifest.schema_version},
            created_by=actor,
        )
        if approve:
            binding = repository.review_binding(
                binding["binding_id"], decision="approve", reviewer=actor,
                comment="Approved reviewed Capability semantic binding manifest",
            )
        created.append(binding)
    return {
        "status": "complete",
        "binding_count": len(created) + len(unchanged),
        "created_count": len(created),
        "unchanged_count": len(unchanged),
        "bindings": created + unchanged,
    }
