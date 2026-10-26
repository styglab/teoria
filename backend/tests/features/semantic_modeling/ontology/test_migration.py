from pathlib import Path
from teoria.features.semantic_modeling.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.features.semantic_modeling.registry.loader import RegistryLoader


async def test_migration_requires_classification_of_every_runtime_object():
    catalog = RegistryLoader(Path("backend/tests/fixtures/registry")).load()
    manifest = OntologyMigrationManifest(schema_version="1.0", source_registry_release="fixture",
        target_ontology="example", classifications={"RUNTIME_PROJECTION": "Runtime only"},
        objects={f"example.{name}": {"classification": "RUNTIME_PROJECTION", "migration_status": "runtime_contract",
                                  "rationale": "A runtime projection is not a business concept"} for name in ("record", "group")})
    report = await build_migration_report(catalog, manifest)
    assert report["status"] == "valid" and report["registry_object_count"] == 2
    del manifest.objects["example.group"]
    report = await build_migration_report(catalog, manifest)
    assert report["status"] == "invalid" and report["missing_objects"] == ["example.group"]
