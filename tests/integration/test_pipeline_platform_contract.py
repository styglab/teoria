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
    assert {
        "contracts",
        "contract_suppliers",
        "public_organizations",
        "contract_demand_organizations",
        "bid_awards",
        "bid_opening_participants",
    } <= {relation.id for relation in source.relations}


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


def test_bid_notice_organization_history_has_supporting_indexes() -> None:
    migration = (
        ROOT / "pipelines" / "database" / "migrations"
        / "038_bid_notice_organization_search.sql"
    ).read_text(encoding="utf-8")

    assert "notice_organization_code, notice_published_at DESC" in migration
    assert "demand_organization_code, notice_published_at DESC" in migration


def test_public_organization_name_search_has_trigram_index() -> None:
    migration = (
        ROOT / "pipelines" / "database" / "migrations"
        / "039_public_organization_name_search.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    assert "organization_name gin_trgm_ops" in migration


def test_bid_notice_contract_lookup_has_supporting_index() -> None:
    migration = (
        ROOT / "pipelines" / "database" / "migrations"
        / "040_bid_notice_contract_lookup.sql"
    ).read_text(encoding="utf-8")

    assert "notice_number, concluded_date DESC, unified_contract_number DESC" in migration
