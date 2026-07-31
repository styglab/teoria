import os
from datetime import date, datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord
from teoria_pipelines.normalization import normalize_contract_batch
from teoria_pipelines.persistence import PostgresStore


DATABASE_URL = os.environ.get("TEORIA_TEST_DATA_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEORIA_TEST_DATA_DATABASE_URL is not set")


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
    assert store.save_raw_records(batch.records) == 1
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
