from pathlib import Path

from teoria.binding.capability_manifest import CapabilityBindingManifest
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


def test_capability_binding_manifest_references_real_contract_fields() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = CapabilityBindingManifest.load(ROOT / "ontology-migrations" / "capability-bindings-v1.yaml")

    assert manifest.validate_catalog(catalog) == []
    assert len(manifest.bindings) == 11
    amount_bindings = [item for item in manifest.bindings if item.ontology_stable_key == "procurement.Contract.amount"]
    assert {item.purpose for item in amount_bindings} == {"analytics", "realtime"}


def test_unified_capability_bindings_target_the_teoria_namespace() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = CapabilityBindingManifest.load(
        ROOT / "ontology-migrations" / "teoria-capability-bindings-v1.yaml"
    )

    assert manifest.validate_catalog(catalog) == []
    assert len(manifest.bindings) == 11
    assert {item.ontology_namespace for item in manifest.bindings} == {"teoria"}
    assert {
        item.ontology_stable_key for item in manifest.bindings
        if item.binding_type == "provides_property"
    } == {"procurement.Contract.currentAmount"}
