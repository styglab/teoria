from pathlib import Path

from teoria.binding.capability_manifest import CapabilityBindingManifest
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


def test_capability_binding_manifest_references_real_contract_fields() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = CapabilityBindingManifest.load(ROOT / "ontology-migrations" / "capability-bindings-v1.yaml")

    assert manifest.validate_catalog(catalog) == []
    assert len(manifest.bindings) == 8
