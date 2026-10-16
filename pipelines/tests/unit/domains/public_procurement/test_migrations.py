from pathlib import Path


def test_contract_operation_progress_migration_cleans_stale_runs_and_dates() -> None:
    migration = (
        Path(__file__).parents[4]
        / "database"
        / "migrations"
        / "043_pipeline_operation_progress.sql"
    ).read_text()

    assert "CREATE TABLE ingestion.pipeline_operation_progress" in migration
    assert "StalePipelineRun" in migration
    assert "contract_date = NULL" in migration
    assert "opening_at = NULL" in migration


def test_relationship_graph_cleanup_drops_snapshot_data_and_functions() -> None:
    migration = (
        Path(__file__).parents[4]
        / "database"
        / "migrations"
        / "075_drop_procurement_relationship_graph.sql"
    ).read_text()

    assert "DROP TABLE IF EXISTS" in migration
    assert "procurement_relationship_graph_versions" in migration
    assert "procurement_relationship_graph_aggregates" in migration
    assert "procurement_relationship_graph_nodes" in migration
    assert "procurement_relationship_graph_overviews" in migration
    assert "publish_procurement_relationship_graph" in migration
