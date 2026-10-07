from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from teoria.binding.capability_manifest import (
    CapabilityBindingManifest,
    apply_capability_binding_manifest,
)
from teoria.registry.loader import RegistryLoader
from teoria.registry.release import RegistryRelease


ROOT = Path(__file__).parents[3]


def test_capability_binding_manifest_references_real_contract_fields() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = CapabilityBindingManifest.load(ROOT / "ontology_migrations" / "applied" / "2026_10_initial_unification" / "capability_bindings_v1.yaml")

    assert manifest.validate_catalog(catalog) == []
    assert len(manifest.bindings) == 11
    amount_bindings = [item for item in manifest.bindings if item.ontology_stable_key == "procurement.Contract.amount"]
    assert {item.purpose for item in amount_bindings} == {"analytics", "realtime"}


def test_unified_capability_bindings_target_the_teoria_namespace() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = CapabilityBindingManifest.load(
        ROOT / "ontology_migrations" / "applied" / "2026_10_initial_unification" / "teoria_capability_bindings_v1.yaml"
    )

    assert manifest.validate_catalog(catalog) == []
    assert len(manifest.bindings) == 11
    assert {item.ontology_namespace for item in manifest.bindings} == {"teoria"}
    assert {
        item.ontology_stable_key for item in manifest.bindings
        if item.binding_type == "provides_property"
    } == {"procurement.Contract.currentAmount"}


class _BindingRepositoryStub:
    def __init__(self, existing: dict | None = None) -> None:
        self.existing = existing
        self.reviews: list[tuple[str, str]] = []
        self.created: list[dict] = []

    def get_published_concept(self, stable_key, *, ontology_namespace=None):
        return {"concept_id": uuid4(), "concept_kind": "object", "stable_key": stable_key}

    def get_active_binding(self, **kwargs):
        return self.existing

    def review_binding(self, binding_id, *, decision, reviewer, comment):
        self.reviews.append((str(binding_id), decision))
        return {**self.existing, "status": "deprecated"}

    def create_capability_binding(self, **kwargs):
        value = {"binding_id": uuid4(), "status": "draft", "target_version": kwargs["registry_version"]}
        self.created.append(kwargs)
        return value


def _single_binding_manifest() -> CapabilityBindingManifest:
    return CapabilityBindingManifest.model_validate({
        "schema_version": "1.0",
        "bindings": [{
            "ontology_namespace": "teoria",
            "ontology_stable_key": "procurement.BidNotice",
            "capability_id": "search_bid_notices",
            "target_scope": "capability",
            "binding_type": "supports",
        }],
    })


def test_approved_capability_binding_requires_registry_release() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()

    with pytest.raises(ValueError, match="immutable Registry release"):
        apply_capability_binding_manifest(
            _BindingRepositoryStub(), catalog, _single_binding_manifest(),
            actor="user:test", approve=True,
        )


def test_replaces_draft_target_with_released_capability_binding() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    catalog.release = RegistryRelease(
        version="2026.10.07.9",
        git_commit="abc123",
        checksum="sha256:test",
        published_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    repository = _BindingRepositoryStub({
        "binding_id": uuid4(), "status": "approved", "target_version": "draft",
    })

    result = apply_capability_binding_manifest(
        repository, catalog, _single_binding_manifest(),
        actor="user:test", approve=False,
    )

    assert result["replaced_count"] == 1
    assert repository.reviews[0][1] == "deprecate"
    assert repository.created[0]["registry_version"] == "2026.10.07.9"
