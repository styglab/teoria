from pathlib import Path

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.registry.compatibility import validate_capability_compatibility

REGISTRIES = Path("backend/tests/fixtures/registry")


def test_capability_version_checksum_and_semantic_compatibility():
    catalog = RegistryLoader(REGISTRIES).load()
    capability = catalog.capabilities["search_records"]
    assert catalog.capability_versions[(capability.id, capability.version)] is capability
    assert catalog.capability_checksums[(capability.id, capability.version)].startswith("sha256:")
    missing = validate_capability_compatibility(catalog, [])
    assert all(row["status"] == "incompatible" for row in missing)
    assert missing[0]["missing_required"][0]["stable_key"] == "example.record"
    ontology = {"content": {"objects": [{"stable_key": "example.record", "properties": [
        {"stable_key": "example.created_date", "value_type": "boolean"}]}], "relationships": []}}
    bindings = [{"capability_id": "search_records", "target_scope": "input",
                 "field_path": "from_date", "ontology_stable_key": "example.created_date"}]
    report = next(r for r in validate_capability_compatibility(catalog, [ontology], bindings)
                  if r["capability_id"] == capability.id)
    assert report["status"] == "incompatible"
    assert report["type_mismatches"][0]["actual_type"] == "date"
    assert all(r["status"] == "compatible" for r in validate_capability_compatibility(catalog, [ontology]))
