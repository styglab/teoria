from pathlib import Path

from teoria.ontology.migration import OntologyMigrationManifest, build_migration_report
from teoria.registry.loader import RegistryLoader


ROOT = Path(__file__).parents[3]


async def test_current_ontology_v2_migration_manifest_covers_every_registry_object() -> (
    None
):
    catalog = RegistryLoader(Path("archive/procurement_services/platform/registries")).load()
    manifest = OntologyMigrationManifest.load(
        ROOT
        / "ontology_migrations"
        / "pending"
        / "2026_10_archive_bid_document_processing"
        / "ontology_v2.yaml"
    )

    report = await build_migration_report(catalog, manifest)

    assert report["status"] == "valid"
    assert report["registry_object_count"] == 38
    assert report["manifest_object_count"] == 38
    assert report["missing_objects"] == []
    assert report["unknown_objects"] == []
    assert report["classification_counts"] == {
        "ASSESSMENT_RESULT": 3,
        "BUSINESS_CONCEPT": 21,
        "RUNTIME_PROJECTION": 14,
    }
