"""Exercise the cleanup against an isolated, restored pre-099 Data DB.

The dedicated opt-in database must contain migrations through 098. Every test
rolls back its changes, including DDL; never use the production database URL.
"""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

DATABASE_URL = os.environ.get("TEORIA_TEST_SCHEMA_CLEANUP_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="Isolated pre-099 database is not configured"
)
MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "backend/migrations/data/099_remove_retired_procurement_storage.sql"
)


@pytest.fixture
async def cleanup_connection():
    async with (
        await psycopg.AsyncConnection.connect(DATABASE_URL or "") as connection,
        connection.transaction(force_rollback=True),
    ):
        row = await (
            await connection.execute(
                "SELECT to_regclass('public_procurement.contracts')"
            )
        ).fetchone()
        if row[0] is None:
            pytest.skip("Cleanup verification requires a pre-099 restored database")
        yield connection


async def relation_exists(connection, name):
    return (
        await (await connection.execute("SELECT to_regclass(%s)", (name,))).fetchone()
    )[0] is not None


async def test_cleanup_preserves_goods_identity_and_active_storage(cleanup_connection):
    connection = cleanup_connection
    notice_number = "cleanup_test_" + uuid4().hex
    await connection.execute(
        "INSERT INTO public_procurement.bid_notices "
        "(notice_number,notice_order,work_type,source_record_hash,source_payload) "
        "VALUES (%s,'000','goods',%s,'{}'::jsonb)",
        (notice_number, "a" * 64),
    )
    before = await (
        await connection.execute(
            "SELECT (SELECT count(*) FROM legal_information.law_snapshot),"
            "(SELECT count(*) FROM public_procurement.specification_processing_runs),"
            "(SELECT count(*) FROM ingestion.pipeline_checkpoints)"
        )
    ).fetchone()
    await connection.execute(MIGRATION.read_text())
    assert not await relation_exists(connection, "public_procurement.contracts")
    assert not await relation_exists(
        connection, "public_procurement.bid_notice_documents"
    )
    assert not await relation_exists(
        connection, "public_procurement.runtime_bid_notices"
    )
    assert await relation_exists(connection, "ingestion.raw_provider_payloads")
    assert await relation_exists(
        connection, "public_procurement.specification_processing_artifacts"
    )
    assert await relation_exists(connection, "mlops_demo.customers")
    after = await (
        await connection.execute(
            "SELECT (SELECT count(*) FROM legal_information.law_snapshot),"
            "(SELECT count(*) FROM public_procurement.specification_processing_runs),"
            "(SELECT count(*) FROM ingestion.pipeline_checkpoints)"
        )
    ).fetchone()
    assert after == before
    assert (
        await (
            await connection.execute(
                "SELECT work_type FROM public_procurement.bid_notices WHERE notice_number=%s",
                (notice_number,),
            )
        ).fetchone()
    )[0] == "goods"
    assert await relation_exists(
        connection, "public_procurement.bid_notice_latest_versions"
    )
    assert await relation_exists(
        connection, "public_procurement.bid_notice_lineage_summaries"
    )
    # Revision triggers must still work after legacy views and tables are gone.
    await connection.execute(
        "INSERT INTO public_procurement.bid_notices "
        "(notice_number,notice_order,work_type,source_record_hash,source_payload) "
        "VALUES (%s,'001','goods',%s,'{}'::jsonb)",
        (notice_number, "c" * 64),
    )
    latest = await (
        await connection.execute(
            "SELECT notice_order FROM public_procurement.bid_notice_latest_versions "
            "WHERE notice_number=%s",
            (notice_number,),
        )
    ).fetchone()
    assert latest[0] == "001"


async def test_cleanup_refuses_populated_retired_storage(cleanup_connection):
    connection = cleanup_connection
    await connection.execute(
        "INSERT INTO public_procurement.contracts "
        "(unified_contract_number,contract_type,source_record_hash) "
        "VALUES (%s,'goods',%s)",
        ("cleanup_test_" + uuid4().hex, "b" * 64),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="is not empty"):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    assert await relation_exists(connection, "public_procurement.contracts")
    assert await relation_exists(connection, "public_procurement.runtime_contracts")


async def test_unknown_dependency_rolls_back_all_schema_removals(cleanup_connection):
    connection = cleanup_connection
    await connection.execute("CREATE SCHEMA cleanup_dependency_test")
    await connection.execute(
        "CREATE VIEW cleanup_dependency_test.contract_reference AS "
        "SELECT unified_contract_number FROM public_procurement.contracts"
    )
    with pytest.raises(psycopg.errors.DependentObjectsStillExist):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    assert await relation_exists(connection, "public_procurement.contracts")
    assert await relation_exists(connection, "public_procurement.runtime_bid_notices")
    assert await relation_exists(
        connection, "cleanup_dependency_test.contract_reference"
    )


async def test_cleanup_refuses_stale_nonempty_materialized_projection(
    cleanup_connection,
):
    connection = cleanup_connection
    organization_code = "cleanup_test_" + uuid4().hex
    await connection.execute(
        "INSERT INTO public_procurement.public_organizations (organization_code,organization_name) "
        "VALUES (%s,'Cleanup fixture')",
        (organization_code,),
    )
    await connection.execute(
        "REFRESH MATERIALIZED VIEW public_procurement.procurement_entity_search_index"
    )
    await connection.execute(
        "DELETE FROM public_procurement.public_organizations WHERE organization_code=%s",
        (organization_code,),
    )
    count = await (
        await connection.execute(
            "SELECT count(*) FROM public_procurement.procurement_entity_search_index"
        )
    ).fetchone()
    assert count[0] > 0
    with pytest.raises(psycopg.errors.RaiseException, match="is not empty"):
        async with connection.transaction():
            await connection.execute(MIGRATION.read_text())
    assert await relation_exists(
        connection, "public_procurement.procurement_entity_search_index"
    )


async def test_cleanup_can_be_replayed_without_affecting_preserved_relations(
    cleanup_connection,
):
    connection = cleanup_connection
    await connection.execute(MIGRATION.read_text())
    await connection.execute(MIGRATION.read_text())
    assert await relation_exists(connection, "public_procurement.bid_notices")
    assert await relation_exists(connection, "legal_information.law")
    assert await relation_exists(connection, "ingestion.pipeline_runs")
