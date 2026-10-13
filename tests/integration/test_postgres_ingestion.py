import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord
from teoria_pipelines.domains.public_procurement.contracts.normalization import normalize_contract_batch
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
            "SELECT count(*) FROM ingestion.raw_provider_observations WHERE execution_id=%s",
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


def test_same_raw_payload_is_deduplicated_across_pipeline_executions() -> None:
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
        payload_count = connection.execute(
            "SELECT count(*) FROM ingestion.raw_provider_payloads "
            "WHERE connector_id=%s AND operation_id=%s AND source_record_hash=%s",
            ("pps_contract_api", "list_goods_contracts", source_record_hash),
        ).fetchone()[0]
        observation_count = connection.execute(
            "SELECT count(*) FROM ingestion.raw_provider_observations "
            "WHERE connector_id=%s AND operation_id=%s AND source_record_hash=%s",
            ("pps_contract_api", "list_goods_contracts", source_record_hash),
        ).fetchone()[0]

    assert payload_count == 1
    assert observation_count == 2


def test_opening_completion_matches_selected_business_numbers() -> None:
    from teoria_pipelines.domains.public_procurement.bid_results.normalization import normalize_bid_result_batch
    from teoria_pipelines.domains.public_procurement.bid_results.selection import select_participants
    store = PostgresStore(DATABASE_URL or '')
    execution_id = uuid4()
    window = CollectionWindow(date(2026, 10, 12), date(2026, 10, 12))
    store.start_run(execution_id, 'opening_completion_regression', window)
    key = {'bidNtceNo': f'TEST-OPENING-{execution_id.hex}', 'bidNtceOrd': '000', 'bidClsfcNo': '1', 'rbidNo': '000'}
    def record(operation, payload, source_hash):
        return RawProviderRecord(uuid4(), execution_id, 'pps_bid_result_api', operation, window,
                                 datetime.now(timezone.utc), source_hash, {**key, **payload})
    award = record('list_service_bid_awards', {'prtcptCnum': '7', 'bidwinnrBizno': '1000000001'}, 'award-coverage')
    awards = ExtractedBatch(execution_id, window, [award])
    openings = ExtractedBatch(execution_id, window, [record('list_completed_opening_results',
        {'prcbdrBizno': f'{1000000000+i}', 'opengRank': str(i if i <= 5 else 0)}, f'participant-{i}')
        for i in range(1, 8)])
    store.upsert_bid_results(normalize_bid_result_batch(awards))
    store.enqueue_bid_opening_enrichment(awards.records)
    store.replace_bid_opening_participants(awards.records, normalize_bid_result_batch(select_participants(awards, openings)))
    store.mark_bid_openings_checked(awards.records, openings.records, execution_id)
    store.finish_bid_opening_enrichment(awards.records, [])
    with psycopg.connect(DATABASE_URL) as c:
        row = c.execute("SELECT q.status,c.participant_count,cardinality(c.selected_business_numbers) FROM ingestion.bid_opening_enrichment_queue q JOIN ingestion.bid_opening_collection_status c USING(notice_number,notice_order,bid_classification_number,rebid_number) WHERE q.notice_number=%s", (key['bidNtceNo'],)).fetchone()
        assert row == ('completed', 7, 5)
        # Equal counts with a wrong identity must not pass.
        c.execute("UPDATE public_procurement.bid_opening_participants SET business_registration_number='9999999999' WHERE notice_number=%s AND business_registration_number='1000000002'", (key['bidNtceNo'],))
    store.finish_bid_opening_enrichment(awards.records, [])
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM ingestion.bid_opening_enrichment_queue WHERE notice_number=%s", (key['bidNtceNo'],)).fetchone()[0] == 'retry_wait'
        c.execute("UPDATE ingestion.bid_opening_collection_status SET selected_business_numbers=NULL WHERE notice_number=%s", (key['bidNtceNo'],))
    store.finish_bid_opening_enrichment(awards.records, [])
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM ingestion.bid_opening_enrichment_queue WHERE notice_number=%s", (key['bidNtceNo'],)).fetchone()[0] == 'retry_wait'
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE ingestion.bid_opening_enrichment_queue SET award_source_record_hash='changed-award',status='pending' WHERE notice_number=%s", (key['bidNtceNo'],))
    store.finish_bid_opening_enrichment(awards.records, [])
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM ingestion.bid_opening_enrichment_queue WHERE notice_number=%s", (key['bidNtceNo'],)).fetchone()[0] == 'pending'


def test_asset_context_output_contract_and_reader_permissions() -> None:
    """Only explicit pipeline outputs get status; runtime cannot inspect raw ingestion."""
    store = PostgresStore(DATABASE_URL or '')
    execution = uuid4()
    window = CollectionWindow(date(2026, 10, 13), date(2026, 10, 13))
    store.start_run(execution, 'pps_contract_incremental', window)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("UPDATE ingestion.pipeline_runs SET status='completed',finished_at=now(),contract_count=7 WHERE execution_id=%s", (execution,))
        runs_oid,payload_oid=connection.execute("SELECT 'ingestion.pipeline_runs'::regclass::oid,'ingestion.raw_provider_payloads'::regclass::oid").fetchone()
        connection.execute("SET ROLE teoria_runtime")
        row=connection.execute("SELECT status,contract_count FROM public_procurement.runtime_asset_collection_status WHERE relation_name='contracts' AND pipeline_id='pps_contract_incremental'").fetchone()
        assert row==('completed',7)
        assert connection.execute("SELECT count(*) FROM public_procurement.runtime_asset_collection_status WHERE relation_name='contracts_neighbor'").fetchone()[0]==0
        assert not connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT')",(runs_oid,)).fetchone()[0]
        assert not connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT')",(payload_oid,)).fetchone()[0]
