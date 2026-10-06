from pathlib import Path

from teoria.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


def test_ontology_v2_migration_manifest_covers_every_legacy_object() -> None:
    catalog = RegistryLoader(ROOT / "registries").load()
    manifest = OntologyMigrationManifest.load(ROOT / "ontology_migrations/ontology_v2.yaml")

    report = build_migration_report(catalog, manifest)

    assert report["status"] == "valid"
    assert report["registry_object_count"] == 41
    assert report["manifest_object_count"] == 41
    assert report["missing_objects"] == []
    assert report["unknown_objects"] == []
    assert report["classification_counts"] == {
        "ASSESSMENT_RESULT": 9,
        "BUSINESS_CONCEPT": 23,
        "RUNTIME_PROJECTION": 9,
    }
