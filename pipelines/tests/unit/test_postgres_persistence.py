from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from teoria_pipelines.models import CollectionWindow, RawProviderRecord
from teoria_pipelines.persistence.postgres import PostgresStore


def test_raw_payload_deduplication_migration_backfills_before_legacy_drop() -> None:
    migrations = Path(__file__).parents[2] / "database" / "migrations"
    deduplication = (
        migrations / "036_deduplicate_raw_provider_payloads.sql"
    ).read_text()
    legacy_drop = (migrations / "037_drop_legacy_raw_provider_records.sql").read_text()

    assert "INSERT INTO ingestion.raw_provider_payloads" in deduplication
    assert "INSERT INTO ingestion.raw_provider_observations" in deduplication
    assert "raw provider observation backfill count mismatch" in deduplication
    assert "raw provider payload backfill count mismatch" in deduplication
    assert "DROP TABLE ingestion.raw_provider_records" not in deduplication
    assert "DROP TABLE ingestion.raw_provider_records" in legacy_drop


async def test_backfill_gap_claim_stops_after_maximum_attempts() -> None:
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    connection.execute.return_value.fetchall.return_value = []

    with patch(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        await PostgresStore("postgresql://unused").claim_backfill_gaps(
            "pps_contract_backfill_2021_2026",
            1,
            retry_days=1,
            max_attempts=15,
        )

    sql, parameters = connection.execute.call_args.args
    assert "attempts<%s" in sql
    assert parameters == ("pps_contract_backfill_2021_2026", 15, 1, 1)


async def test_raw_storage_separates_deduplicated_payload_from_observation() -> None:
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    cursor = MagicMock()
    cursor.__aenter__.return_value = cursor
    cursor.executemany = AsyncMock()
    cursor.rowcount = 1
    connection.cursor.return_value = cursor
    execution_id = uuid4()
    record = RawProviderRecord(
        raw_record_id=uuid4(),
        execution_id=execution_id,
        connector_id="pps_contract_api",
        operation_id="list_goods_contracts",
        window=CollectionWindow(date(2026, 9, 15), date(2026, 9, 15)),
        fetched_at=datetime.now(timezone.utc),
        source_record_hash="hash",
        payload={"id": "contract"},
    )

    with patch(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        assert (
            await PostgresStore("postgresql://unused").save_raw_records([record])
        ) == 1

    payload_call, observation_call = cursor.executemany.call_args_list
    assert "INSERT INTO ingestion.raw_provider_payloads" in payload_call.args[0]
    assert (
        "ON CONFLICT (connector_id, operation_id, source_record_hash)"
        in payload_call.args[0]
    )
    assert "INSERT INTO ingestion.raw_provider_observations" in observation_call.args[0]
    assert (
        "ON CONFLICT (execution_id, connector_id, operation_id"
        in observation_call.args[0]
    )
