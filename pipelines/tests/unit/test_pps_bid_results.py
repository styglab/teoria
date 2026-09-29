import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from teoria_pipelines.connectors.pps_bid_results import PPSBidResultClient
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow, RawProviderRecord
from teoria_pipelines.normalization import (
    normalize_bid_award_record,
    normalize_opening_participant_record,
)
from teoria_pipelines.tasks.pps_bid_results import (
    select_competitive_opening_participants,
    split_opening_award_chunks,
)
from teoria_pipelines.validator import PipelineValidator
from teoria_pipelines.verification import verify_connector


PIPELINES = Path(__file__).parents[2]


def _record(operation_id: str, payload: dict) -> RawProviderRecord:
    return RawProviderRecord(
        raw_record_id=uuid4(), execution_id=uuid4(), connector_id="pps_bid_result_api",
        operation_id=operation_id,
        window=CollectionWindow(date(2026, 9, 1), date(2026, 9, 1)),
        fetched_at=datetime.now(timezone.utc), source_record_hash="result-hash", payload=payload,
    )


def test_bid_result_connector_and_pipeline_are_complete() -> None:
    catalog = PipelineLoader(PIPELINES).load()
    operations = {item.id for item in catalog.connectors["pps_bid_result_api"].connector.operations}
    assert operations == {
        "list_goods_bid_awards", "list_construction_bid_awards",
        "list_service_bid_awards", "list_foreign_bid_awards",
        "list_completed_opening_results",
    }
    assert catalog.pipelines["pps_bid_result_ingestion"].sink.relations == [
        "bid_awards", "bid_opening_participants"
    ]
    assert PipelineValidator().validate(catalog) == []


@pytest.mark.asyncio
async def test_bid_result_build_injects_json_response_type() -> None:
    catalog = PipelineLoader(PIPELINES).load()
    result = await verify_connector(
        catalog, connector_id="pps_bid_result_api", operation_id="list_goods_bid_awards",
        profile="build", input_data={"query": {
            "numOfRows": 10, "pageNo": 1, "inqryDiv": "2",
            "inqryBgnDt": "202609010000", "inqryEndDt": "202609012359",
        }},
    )
    assert result["status"] == "passed"
    assert result["prepared_request"]["query"]["type"] == "json"


def test_normalizes_award_times_as_korean_source_time() -> None:
    result = normalize_bid_award_record(_record("list_foreign_bid_awards", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
        "bidClsfcNo": "1", "rbidNo": "000", "prtcptCnum": "2",
        "bidwinnrBizno": "123-45-67890", "sucsfbidAmt": "1,200,000",
        "sucsfbidRate": "91.23", "rlOpengDt": "2026-09-01 10:00:00",
        "rgstDt": "2026-09-01 11:00:00", "FnlSucsfDate": "2026-09-01",
    }))
    assert result["work_type"] == "foreign"
    assert result["winner_business_registration_number"] == "1234567890"
    assert result["winning_amount"] == Decimal("1200000")
    assert result["opening_at"].utcoffset().total_seconds() == 9 * 3600
    assert result["final_award_date"] == date(2026, 9, 1)


def test_normalizes_provider_numeric_hash_placeholder_as_unavailable() -> None:
    record = _record("list_service_bid_awards", {
        "bidNtceNo": "R24BK00000001", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000", "prtcptCnum": "2",
        "sucsfbidAmt": "1000000", "sucsfbidRate": "########",
        "rlOpengDt": "2024-12-26 10:00:00",
    })

    result = normalize_bid_award_record(record)

    assert result["winning_rate"] is None
    assert record.payload["sucsfbidRate"] == "########"


def test_rejects_unknown_non_numeric_decimal_values() -> None:
    with pytest.raises(ValueError, match="invalid decimal value"):
        normalize_bid_award_record(_record("list_service_bid_awards", {
            "bidNtceNo": "R24BK00000001", "bidNtceOrd": "000",
            "bidClsfcNo": "0", "rbidNo": "000", "prtcptCnum": "2",
            "sucsfbidAmt": "1000000", "sucsfbidRate": "not-a-number",
            "rlOpengDt": "2024-12-26 10:00:00",
        }))


def test_normalizes_opening_participant_scores() -> None:
    result = normalize_opening_participant_record(_record("list_completed_opening_results", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000", "prcbdrBizno": "1234567890",
        "opengRank": "1", "bidprcAmt": "1000000", "bidprcrt": "90.1",
        "bidprcDt": "2026-09-01 09:30:00", "bidPrceEvlVal": "9.5",
        "techEvlNaturVal": "80", "techEvlVal": "81.5", "totalEvlAmtVal": "91",
    }))
    assert result["opening_rank"] == 1
    assert result["technical_evaluation_score"] == Decimal("81.5")
    assert result["bid_at"].utcoffset().total_seconds() == 9 * 3600


class _CapturingClient(PPSBidResultClient):
    def __init__(self) -> None:
        class ExecutorContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        self.calls = []
        self.executor = ExecutorContext()
        self.opening_concurrency = 8
        self.opening_request_timeout_seconds = 60
        self._opening_rate_limiter_active = False

    async def _fetch_pages(self, execution_id, window, operation_id, query):
        self.calls.append((operation_id, query))
        from teoria_pipelines.models import ExtractedBatch
        return ExtractedBatch(execution_id=execution_id, window=window, pages=1)


@pytest.mark.asyncio
async def test_opening_api_is_called_once_per_distinct_award_key() -> None:
    client = _CapturingClient()
    payload = {"bidNtceNo": "R26BK00000001", "bidNtceOrd": "000", "bidClsfcNo": "0", "rbidNo": "000"}
    records = [
        _record("list_goods_bid_awards", payload),
        _record("list_goods_bid_awards", payload),
    ]
    result = await client.fetch_opening_results(
        records[0].execution_id, records[0].window, records
    )
    assert client.calls == [("list_completed_opening_results", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000",
    })]
    assert result.successful_awards.records == [records[1]]
    assert result.failed_awards.records == []


@pytest.mark.asyncio
async def test_opening_api_uses_bounded_concurrency() -> None:
    class ConcurrentClient(_CapturingClient):
        def __init__(self) -> None:
            super().__init__()
            self.opening_concurrency = 3
            self.active = 0
            self.maximum_active = 0

        async def _fetch_pages(self, execution_id, window, operation_id, query):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return await super()._fetch_pages(execution_id, window, operation_id, query)

    client = ConcurrentClient()
    records = [_record("list_goods_bid_awards", {
        "bidNtceNo": f"R26BK{number:08d}", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000",
    }) for number in range(10)]
    await client.fetch_opening_results(records[0].execution_id, records[0].window, records)
    assert client.maximum_active == 3


@pytest.mark.asyncio
async def test_opening_api_isolates_timed_out_award() -> None:
    class TimeoutClient(_CapturingClient):
        def __init__(self) -> None:
            super().__init__()
            self.opening_request_timeout_seconds = 0.01

        async def _fetch_pages(self, execution_id, window, operation_id, query):
            if query["bidNtceNo"].endswith("1"):
                await asyncio.sleep(1)
            return await super()._fetch_pages(execution_id, window, operation_id, query)

    client = TimeoutClient()
    records = [_record("list_goods_bid_awards", {
        "bidNtceNo": f"R26BK0000000{number}", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000",
    }) for number in (1, 2)]

    result = await client.fetch_opening_results(
        records[0].execution_id, records[0].window, records
    )

    assert [item.payload["bidNtceNo"] for item in result.successful_awards.records] == [
        "R26BK00000002"
    ]
    assert [item.payload["bidNtceNo"] for item in result.failed_awards.records] == [
        "R26BK00000001"
    ]


def test_opening_awards_are_split_into_restartable_chunks() -> None:
    from teoria_pipelines.models import ExtractedBatch

    records = [_record("list_goods_bid_awards", {
        "bidNtceNo": f"R26BK{number:08d}", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000",
    }) for number in range(205)]
    batch = ExtractedBatch(records[0].execution_id, records[0].window, records)
    chunks = split_opening_award_chunks.fn(batch, 100)
    assert [len(chunk.records) for chunk in chunks] == [100, 100, 5]


def test_selects_top_ten_and_rankless_winner_only() -> None:
    from teoria_pipelines.models import ExtractedBatch

    award = _record("list_goods_bid_awards", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
        "bidClsfcNo": "0", "rbidNo": "000", "bidwinnrBizno": "123-45-67890",
    })
    openings = [
        _record("list_completed_opening_results", {
            "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
            "bidClsfcNo": "0", "rbidNo": "000", "prcbdrBizno": business,
            "opengRank": rank,
        })
        for business, rank in [
            ("1111111111", "1"),
            ("2222222222", "10"),
            ("3333333333", "11"),
            ("1234567890", ""),
            ("4444444444", ""),
        ]
    ]

    selected = select_competitive_opening_participants.fn(
        ExtractedBatch(award.execution_id, award.window, [award]),
        ExtractedBatch(award.execution_id, award.window, openings, pages=2),
    )

    assert [item.payload["prcbdrBizno"] for item in selected.records] == [
        "1111111111", "2222222222", "1234567890",
    ]
    assert selected.pages == 2


def test_rejects_non_positive_competitive_rank_limit() -> None:
    from teoria_pipelines.models import ExtractedBatch

    empty = ExtractedBatch(uuid4(), CollectionWindow(date(2026, 9, 1), date(2026, 9, 1)))
    with pytest.raises(ValueError, match="maximum_rank must be positive"):
        select_competitive_opening_participants.fn(empty, empty, 0)
