from unittest.mock import MagicMock, patch
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from teoria_pipelines.models import CollectionWindow, RawProviderRecord
from teoria_pipelines.persistence.postgres import PostgresStore


def test_raw_payload_deduplication_migration_backfills_before_legacy_drop() -> None:
    migrations = Path(__file__).parents[2] / "database" / "migrations"
    deduplication = (migrations / "036_deduplicate_raw_provider_payloads.sql").read_text()
    legacy_drop = (migrations / "037_drop_legacy_raw_provider_records.sql").read_text()

    assert "INSERT INTO ingestion.raw_provider_payloads" in deduplication
    assert "INSERT INTO ingestion.raw_provider_observations" in deduplication
    assert "raw provider observation backfill count mismatch" in deduplication
    assert "raw provider payload backfill count mismatch" in deduplication
    assert "DROP TABLE ingestion.raw_provider_records" not in deduplication
    assert "DROP TABLE ingestion.raw_provider_records" in legacy_drop


def test_raw_storage_separates_deduplicated_payload_from_observation() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.rowcount = 1
    connection.cursor.return_value = cursor
    execution_id = uuid4()
    record = RawProviderRecord(
        raw_record_id=uuid4(), execution_id=execution_id,
        connector_id="pps_contract_api", operation_id="list_goods_contracts",
        window=CollectionWindow(date(2026, 9, 15), date(2026, 9, 15)),
        fetched_at=datetime.now(timezone.utc), source_record_hash="hash",
        payload={"id": "contract"},
    )

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        assert PostgresStore("postgresql://unused").save_raw_records([record]) == 1

    payload_call, observation_call = cursor.executemany.call_args_list
    assert "INSERT INTO ingestion.raw_provider_payloads" in payload_call.args[0]
    assert "ON CONFLICT (connector_id, operation_id, source_record_hash)" in payload_call.args[0]
    assert "INSERT INTO ingestion.raw_provider_observations" in observation_call.args[0]
    assert "ON CONFLICT (execution_id, connector_id, operation_id" in observation_call.args[0]


def test_parser_claim_reclaims_expired_processing_lease() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        PostgresStore("postgresql://unused").claim_documents_for_parsing(
            10, "2.1.1", max_attempts=3,
        )

    sql, parameters = connection.execute.call_args.args
    assert "parse_status='processing' AND updated_at <= now()-interval '1 hour'" in sql
    assert (
        "parse_status IN ('parsed','unsupported') "
        "AND parser_version IS DISTINCT FROM %s"
    ) in sql
    assert "CASE WHEN c.parser_version_changed THEN 1" in sql
    assert parameters == ("2.1.1", 3, "2.1.1", 10)


def test_extraction_selection_prioritizes_latest_active_notice_revision() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchall.return_value = []

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        PostgresStore("postgresql://unused").list_notices_for_eligibility_extraction(10)

    sql, parameters = connection.execute.call_args.args
    assert "n.notice_kind_name IS DISTINCT FROM '취소공고'" in sql
    assert "COALESCE(n.notice_kind_name, '') !~ '(평가|개찰|낙찰|계약).*(결과|결정)'" in sql
    assert "COALESCE(n.notice_name, '') !~" in sql
    assert "FROM public_procurement.bid_notices newer" in sql
    assert "ORDER BY n.notice_published_at DESC NULLS LAST" in sql
    assert parameters == [3, 3, 10]


def test_eligibility_claim_uses_one_hour_lease() -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = (1,)

    with patch("teoria_pipelines.persistence.postgres.psycopg.connect",
               return_value=connection):
        claimed = PostgresStore("postgresql://unused").claim_eligibility_extraction(
            {"notice_number": "R1", "notice_order": "000"}, "fingerprint", "2.3.15"
        )

    sql, parameters = connection.execute.call_args.args
    assert claimed is True
    assert "status='processing'" in sql
    assert "started_at<=now()-interval '1 hour'" in sql
    assert parameters[1:] == ("R1", "000", "fingerprint", "2.3.15")
