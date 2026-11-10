from pathlib import Path
from teoria.platform.ontology.contracts.ontology_migration import OntologyMigrationManifest, build_migration_report
from teoria.platform.ontology.contracts.loader import RegistryLoader


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


async def test_native_goods_draft_and_runtime_projection_remain_distinct():
    manifest = OntologyMigrationManifest.load(Path(
        'backend/authoring/ontology_migrations/pending/2026_11_goods_runtime_requirements/ontology_v2.yaml'))
    catalog = RegistryLoader(Path('backend/contracts/runtime')).load()
    report = await build_migration_report(catalog, manifest)
    assert report['status'] == 'valid' and report['registry_object_count'] == 1
    assert report['manifest_object_count'] == 1 and report['draft_object_count'] == 4
    rows = {row['stable_key']:row for row in report['draft_objects']}
    assert rows['goods.server']['migration_status'] == 'planned'
    assert rows['goods.memory_module']['classification'] == 'BUSINESS_CONCEPT'
    assert rows['goods.item_type']['classification'] == 'DEPRECATED'
    assert rows['goods.characteristic_definition']['migration_status'] == 'deprecated'
    assert all(row['published_target_verification'] == 'not_checked' for row in rows.values())
