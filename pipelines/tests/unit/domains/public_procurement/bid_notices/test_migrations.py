from pathlib import Path


def test_bid_notice_search_migration_materializes_latest_version_and_trigrams() -> None:
    migration = (
        Path(__file__).parents[5]
        / "database"
        / "migrations"
        / "042_bid_notice_runtime_search.sql"
    ).read_text()

    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
    assert migration.count("gin_trgm_ops") == 4
    assert "CREATE TABLE public_procurement.bid_notice_latest_versions" in migration
    assert "CREATE TRIGGER bid_notices_sync_latest_version" in migration
    assert "row_number() OVER" not in migration
