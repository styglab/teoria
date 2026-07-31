from pathlib import Path

from teoria.registry.loader import RegistryLoader
from teoria_pipelines.integration import PlatformIntegrationValidator
from teoria_pipelines.loader import PipelineLoader


ROOT = Path(__file__).parents[2]


def test_pipeline_sink_matches_platform_database_source() -> None:
    pipeline_catalog = PipelineLoader(ROOT / "pipelines").load()
    platform_catalog = RegistryLoader(ROOT / "platform" / "registries").load()

    assert PlatformIntegrationValidator().validate(pipeline_catalog, platform_catalog) == []

    source = platform_catalog.sources["teoria_public_procurement"].source
    assert source.type == "database"
    assert {relation.id for relation in source.relations} == {
        "contracts",
        "contract_suppliers",
        "public_organizations",
        "contract_demand_organizations",
    }


def test_database_migration_contains_every_published_source_field() -> None:
    catalog = RegistryLoader(ROOT / "platform" / "registries").load()
    source = catalog.sources["teoria_public_procurement"].source
    migration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "pipelines" / "database" / "migrations").glob("*.sql"))
    )

    for relation in source.relations:
        assert relation.relation in migration
        for field in relation.fields:
            assert field.id in migration
