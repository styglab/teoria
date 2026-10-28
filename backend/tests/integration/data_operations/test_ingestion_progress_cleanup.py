"""Guard migration 100 against an isolated, restored pre-100 Data DB."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

DATABASE_URL = os.environ.get("TEORIA_TEST_INGESTION_PRUNE_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Isolated pre-100 database is not configured"
)
MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "backend/migrations/data/100_prune_unused_ingestion_progress.sql"
)
COUNTERS = (
    "contract_count",
    "notice_count",
    "document_count",
    "award_count",
    "opening_participant_count",
    "notice_outcome_count",
)


@pytest.fixture
async def cleanup_connection():
    async with (
        await psycopg.AsyncConnection.connect(DATABASE_URL or "") as connection,
        connection.transaction(force_rollback=True),
    ):
        row = await (
            await connection.execute(
                "SELECT to_regclass('ingestion.pipeline_operation_progress')"
            )
        ).fetchone()
        if row[0] is None:
            pytest.skip("A restored pre-100 database is required")
        yield connection


async def runs_fingerprint(connection):
    return await (
        await connection.execute(
            "SELECT count(*),md5(COALESCE(string_agg((to_jsonb(t)-%s::text[])::text,'' "
            "ORDER BY execution_id),'')) FROM ingestion.pipeline_runs t",
            (list(COUNTERS),),
        )
    ).fetchone()


async def test_cleanup_preserves_runs_raw_sources_and_checkpoints(cleanup_connection):
    connection = cleanup_connection
    before = await runs_fingerprint(connection)
    checkpoint_count = (
        await (
            await connection.execute(
                "SELECT count(*) FROM ingestion.pipeline_checkpoints"
            )
        ).fetchone()
    )[0]
    await connection.execute(MIGRATION.read_text())
    assert await runs_fingerprint(connection) == before
    remaining = await (
        await connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='ingestion' AND table_name='pipeline_runs'"
        )
    ).fetchall()
    names = {row[0] for row in remaining}
    assert "raw_record_count" in names
    assert not names.intersection(COUNTERS)
    assert (
        await (
            await connection.execute(
                "SELECT to_regclass('ingestion.pipeline_operation_progress')"
            )
        ).fetchone()
    )[0] is None
    for name in (
        "raw_provider_payloads",
        "raw_provider_observations",
        "law_raw_payloads",
        "law_raw_observations",
        "pipeline_backfill_gaps",
        "schema_migrations",
    ):
        assert (
            await (
                await connection.execute(
                    "SELECT to_regclass(%s)", ("ingestion." + name,)
                )
            ).fetchone()
        )[0] is not None
    assert (
        await (
            await connection.execute(
                "SELECT count(*) FROM ingestion.pipeline_checkpoints"
            )
        ).fetchone()
    )[0] == checkpoint_count


async def test_recorded_operation_progress_prevents_cleanup(cleanup_connection):
    connection = cleanup_connection
    await connection.execute(
        "INSERT INTO ingestion.pipeline_operation_progress "
        "(pipeline_id,window_start,window_end,operation_id,execution_id,raw_record_count) "
        "VALUES ('cleanup_fixture','2026-10-28','2026-10-28','fixture',%s,1)",
        (uuid4(),),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="progress is not empty"):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    assert (
        await (
            await connection.execute(
                "SELECT count(*) FROM ingestion.pipeline_operation_progress"
            )
        ).fetchone()
    )[0] == 1


@pytest.mark.parametrize("counter", COUNTERS)
async def test_nonzero_legacy_counter_prevents_information_loss(
    cleanup_connection, counter
):
    connection = cleanup_connection
    execution_id = uuid4()
    await connection.execute(
        sql.SQL(
            "INSERT INTO ingestion.pipeline_runs "
            "(execution_id,pipeline_id,window_start,window_end,started_at,status,{}) "
            "VALUES (%s,'cleanup_fixture','2026-10-28','2026-10-28',now(),'completed',1)"
        ).format(sql.Identifier(counter)),
        (execution_id,),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="contains information"):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    value = await (
        await connection.execute(
            sql.SQL(
                "SELECT {} FROM ingestion.pipeline_runs WHERE execution_id=%s"
            ).format(sql.Identifier(counter)),
            (execution_id,),
        )
    ).fetchone()
    assert value[0] == 1


async def test_unknown_counter_dependency_rolls_back_progress_drop(cleanup_connection):
    connection = cleanup_connection
    await connection.execute("CREATE SCHEMA cleanup_dependency_test")
    await connection.execute(
        "CREATE VIEW cleanup_dependency_test.counter_reference AS "
        "SELECT contract_count FROM ingestion.pipeline_runs"
    )
    with pytest.raises(psycopg.errors.DependentObjectsStillExist):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    assert (
        await (
            await connection.execute(
                "SELECT to_regclass('ingestion.pipeline_operation_progress')"
            )
        ).fetchone()
    )[0] is not None


async def test_cleanup_is_replayable(cleanup_connection):
    connection = cleanup_connection
    await connection.execute(MIGRATION.read_text())
    await connection.execute(MIGRATION.read_text())
    assert "raw_record_count" in {
        row[0]
        for row in await (
            await connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ingestion' AND table_name='pipeline_runs'"
            )
        ).fetchall()
    }
