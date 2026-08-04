import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord
from teoria_pipelines.normalization import normalize_contract_batch
from teoria_pipelines.persistence import PostgresStore


DATABASE_URL = os.environ.get("TEORIA_TEST_DATA_DATABASE_URL")
MIGRATIONS = Path(__file__).parents[2] / "pipelines" / "database" / "migrations"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEORIA_TEST_DATA_DATABASE_URL is not set")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    store = PostgresStore(DATABASE_URL or "")
    store.apply_migrations(MIGRATIONS)


def test_migrations_are_recorded_and_idempotent() -> None:
    store = PostgresStore(DATABASE_URL or "")

    assert store.apply_migrations(MIGRATIONS) == []
    with psycopg.connect(DATABASE_URL) as connection:
        versions = {
            row[0]
            for row in connection.execute("SELECT version FROM ingestion.schema_migrations")
        }

    assert {
        "001_initial_public_procurement.sql",
        "002_raw_record_execution_identity.sql",
        "003_drop_legacy_raw_record_uniqueness.sql",
        "004_standardize_audit_timestamps.sql",
    }.issubset(versions)


def test_mutable_tables_use_standard_audit_timestamps() -> None:
    expected = {
        ("ingestion", "pipeline_checkpoints"),
        ("public_procurement", "contracts"),
        ("public_procurement", "public_organizations"),
        ("public_procurement", "contract_suppliers"),
        ("public_procurement", "contract_demand_organizations"),
    }
    with psycopg.connect(DATABASE_URL) as connection:
        columns = {
            (schema, table, column)
            for schema, table, column in connection.execute(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns "
                "WHERE table_schema IN ('ingestion', 'public_procurement')"
            )
        }

    for schema, table in expected:
        assert (schema, table, "created_at") in columns
        assert (schema, table, "updated_at") in columns
    assert not any(column == "ingested_at" for _, _, column in columns)


def test_raw_normalized_and_checkpoint_writes_are_idempotent() -> None:
    store = PostgresStore(DATABASE_URL or "")
    execution_id = uuid4()
    window = CollectionWindow(date(2026, 7, 1), date(2026, 7, 1))
    store.start_run(execution_id, "pps_contract_ingestion", window)
    record = RawProviderRecord(
        raw_record_id=uuid4(),
        execution_id=execution_id,
        connector_id="pps_contract_api",
        operation_id="list_goods_contracts",
        window=window,
        fetched_at=datetime.now(timezone.utc),
        source_record_hash=uuid4().hex,
        payload={
            "untyCntrctNo": f"test-{execution_id}",
            "cntrctNm": "통합 테스트 계약",
            "cmmnCntrctYn": "N",
            "cntrctDate": "20260701",
            "cntrctInsttCd": "TEST001",
            "cntrctInsttNm": "통합 테스트 기관",
            "corpList": "[1^주계약업체^단독^테스트기업^홍길동^대한민국^100^^담당자^1234567890]",
            "dminsttList": "[1^TEST002^테스트 수요기관^공공기관^계약팀^김담당^02-0000-0000]",
        },
    )
    batch = ExtractedBatch(execution_id=execution_id, window=window, records=[record], pages=1)

    assert store.save_raw_records(batch.records) == 1
    assert store.save_raw_records(batch.records) == 0
    normalized = normalize_contract_batch(batch)
    summary = store.upsert_normalized(normalized)
    store.upsert_normalized(normalized)
    store.update_checkpoint("pps_contract_ingestion", window.end, execution_id)
    store.complete_run(execution_id, summary)

    with psycopg.connect(DATABASE_URL) as connection:
        raw_count = connection.execute(
            "SELECT count(*) FROM ingestion.raw_provider_records WHERE execution_id=%s",
            (execution_id,),
        ).fetchone()[0]
        contract_count = connection.execute(
            "SELECT count(*) FROM public_procurement.contracts WHERE unified_contract_number=%s",
            (f"test-{execution_id}",),
        ).fetchone()[0]
        checkpoint = connection.execute(
            "SELECT cursor_date FROM ingestion.pipeline_checkpoints WHERE pipeline_id=%s",
            ("pps_contract_ingestion",),
        ).fetchone()[0]

    assert raw_count == 1
    assert contract_count == 1
    assert checkpoint == window.end


def test_same_raw_record_is_preserved_across_pipeline_executions() -> None:
    store = PostgresStore(DATABASE_URL or "")
    first_execution_id = uuid4()
    second_execution_id = uuid4()
    source_record_hash = uuid4().hex
    window = CollectionWindow(date(2026, 7, 2), date(2026, 7, 2))

    for execution_id in (first_execution_id, second_execution_id):
        store.start_run(execution_id, "pps_contract_ingestion", window)
        record = RawProviderRecord(
            raw_record_id=uuid4(),
            execution_id=execution_id,
            connector_id="pps_contract_api",
            operation_id="list_goods_contracts",
            window=window,
            fetched_at=datetime.now(timezone.utc),
            source_record_hash=source_record_hash,
            payload={"untyCntrctNo": f"shared-{source_record_hash}"},
        )
        assert store.save_raw_records([record]) == 1

    with psycopg.connect(DATABASE_URL) as connection:
        raw_count = connection.execute(
            "SELECT count(*) FROM ingestion.raw_provider_records "
            "WHERE connector_id=%s AND operation_id=%s AND source_record_hash=%s",
            ("pps_contract_api", "list_goods_contracts", source_record_hash),
        ).fetchone()[0]

    assert raw_count == 2
