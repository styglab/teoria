from datetime import date, datetime, timezone
from uuid import uuid4

from teoria_pipelines.models import CollectionWindow, RawProviderRecord
from teoria_pipelines.normalization import normalize_contract_record


def test_normalizes_contract_supplier_and_demand_organization() -> None:
    execution_id = uuid4()
    record = RawProviderRecord(
        raw_record_id=uuid4(),
        execution_id=execution_id,
        connector_id="pps_contract_api",
        operation_id="list_goods_contracts",
        window=CollectionWindow(date(2026, 7, 1), date(2026, 7, 1)),
        fetched_at=datetime.now(timezone.utc),
        source_record_hash="abc123",
        payload={
            "untyCntrctNo": "20260700001",
            "cntrctNm": "테스트 물품 계약",
            "cmmnCntrctYn": "N",
            "cntrctCnclsDate": "20260701",
            "cntrctDate": "2026-07-01",
            "totCntrctAmt": "1,200,000",
            "cntrctInsttCd": "1230000",
            "cntrctInsttNm": "조달청",
            "cntrctInsttJrsdctnDivNm": "국가기관",
            "corpList": "[1^주계약업체^단독^테스트기업^홍길동^대한민국^100^^담당자^1234567890]",
            "dminsttList": "[1^Z000001^테스트기관^공공기관^계약팀^김담당^02-0000-0000]",
            "rgstDt": "2026-07-01 09:30:00",
        },
    )

    contract, suppliers, demands, organizations = normalize_contract_record(record)

    assert contract["contract_type"] == "goods"
    assert contract["total_amount_currency"] == "KRW"
    assert contract["total_amount"] == 1200000
    assert contract["is_joint_contract"] is False
    assert suppliers[0]["business_registration_number"] == "1234567890"
    assert suppliers[0]["supplier_sequence"] == 1
    assert demands[0]["organization_code"] == "Z000001"
    assert {item["organization_code"] for item in organizations} == {"1230000", "Z000001"}
