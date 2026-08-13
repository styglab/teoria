from datetime import date, datetime, timezone
from uuid import uuid4

from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord
from teoria_pipelines.normalization.pps_bid_notices import (
    normalize_bid_notice_batch,
    parse_industry_main_field_groups,
    parse_industry_reference,
    parse_permitted_industries,
)
from teoria_pipelines.tasks.pps_bid_notices import (
    determine_bid_notice_window,
    safe_object_file_name,
)


def raw(operation_id: str, payload: dict) -> RawProviderRecord:
    return RawProviderRecord(
        raw_record_id=uuid4(), execution_id=uuid4(), connector_id="pps_bid_notice_api",
        operation_id=operation_id, window=CollectionWindow(date(2026, 8, 7), date(2026, 8, 7)),
        fetched_at=datetime.now(timezone.utc), source_record_hash=f"hash-{operation_id}",
        payload=payload,
    )


def test_normalizes_notice_and_discovers_documents() -> None:
    record = raw("list_service_bid_notices", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000",
        "bidNtceNm": "정보시스템 운영 용역", "reNtceYn": "N",
        "bidNtceDt": "202608071000", "bidClseDt": "202608141800",
        "presmptPrce": "100,000,000", "asignBdgtAmt": "110000000",
        "prtcptLmtRgnCd": "11", "prtcptLmtRgnNm": "서울특별시",
        "ntceSpecFileNm1": "공고문.hwpx", "ntceSpecDocUrl1": "https://example.test/a.hwpx",
        "stdNtceDocUrl": "https://example.test/standard.pdf",
    })

    result = normalize_bid_notice_batch(ExtractedBatch(
        execution_id=record.execution_id, window=record.window, records=[record]
    ))

    assert result.notices[0]["work_type"] == "service"
    assert result.notices[0]["notice_number"] == "R26BK00000001"
    assert result.notices[0]["bid_deadline_at"] == datetime(2026, 8, 14, 18, 0)
    assert str(result.notices[0]["estimated_price"]) == "100000000"
    assert result.notices[0]["participation_restriction_region_code"] == "11"
    assert result.notices[0]["participation_restriction_region_name"] == "서울특별시"
    assert {(item["document_slot"], item["file_name"]) for item in result.documents} == {
        ("notice_spec_1", "공고문.hwpx"), ("standard_notice", "표준공고서")
    }


def test_normalizes_notice_enrichment() -> None:
    license_record = raw("list_license_restrictions", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000", "lmtGrpNo": "1",
        "lmtSno": "2", "lcnsLmtNm": "업종제한", "permsnIndstrytyList": "[1468]",
    })
    region_record = raw("list_participation_regions", {
        "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000", "lmtSno": "1",
        "prtcptPsblRgnNm": "서울특별시",
    })

    result = normalize_bid_notice_batch(ExtractedBatch(
        execution_id=license_record.execution_id, window=license_record.window,
        records=[license_record, region_record],
    ))

    assert result.license_restrictions[0]["license_restriction_name"] == "업종제한"
    assert result.participation_regions[0]["participation_region_code"] == "11"
    assert result.participation_regions[0]["participation_region_name"] == "서울특별시"


def test_parses_documented_license_and_permitted_industry_notation() -> None:
    assert parse_industry_reference("액화석유가스판매사업/4617") == {
        "name": "액화석유가스판매사업", "code": "4617",
        "text": "액화석유가스판매사업/4617",
    }
    assert parse_permitted_industries(
        "[액화석유가스충전사업/4615],[액화석유가스집단공급사업/4616]"
    ) == [
        {"name": "액화석유가스충전사업", "code": "4615",
         "text": "액화석유가스충전사업/4615"},
        {"name": "액화석유가스집단공급사업", "code": "4616",
         "text": "액화석유가스집단공급사업/4616"},
    ]


def test_parses_main_industry_fields_as_or_of_and_groups() -> None:
    assert parse_industry_main_field_groups(
        "[1^포장공사^보링.그라우팅.파일공사],[2^토공사]"
    ) == [
        {"sequence": "1", "operator": "all",
         "fields": ["포장공사", "보링.그라우팅.파일공사"]},
        {"sequence": "2", "operator": "all", "fields": ["토공사"]},
    ]


def test_object_file_name_preserves_original_name_and_blocks_path_segments() -> None:
    assert safe_object_file_name("제안요청서.hwp", "abc", ".hwp") == "제안요청서.hwp"
    assert safe_object_file_name("../공고/규격서.pdf", "abc", ".pdf") == "_공고_규격서.pdf"
    assert safe_object_file_name(None, "abc", ".pdf") == "abc.pdf"


def test_bid_notice_window_uses_seoul_calendar_date(monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            assert str(tz) == "Asia/Seoul"
            return datetime(2026, 8, 13, 8, 30, tzinfo=tz)

    monkeypatch.setattr(
        "teoria_pipelines.tasks.pps_bid_notices.datetime", FixedDateTime
    )

    assert determine_bid_notice_window.fn(lookback_days=1) == CollectionWindow(
        date(2026, 8, 13), date(2026, 8, 13)
    )
