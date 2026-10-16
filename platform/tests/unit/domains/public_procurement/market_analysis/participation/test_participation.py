from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.participation.service import (
    execute_bid_notice_participations,
    execute_company_competitor_analysis,
    execute_company_participation_search,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_company_participation_search_and_competitors_share_filters() -> None:
    class Reader:
        async def find(self, catalog, **kwargs):
            return [
                {
                    "bid_notice_id": "N1:000",
                    "notice_name": "정보시스템 사업",
                    "organization_code": "ORG",
                    "organization_name": "기관",
                    "participant_name": "대상",
                    "participation_date": date(2025, 5, 1),
                    "rank": 2,
                    "participant_count": 7,
                    "bid_amount": Decimal("90"),
                    "winning_amount": Decimal("100"),
                    "result": "unsuccessful",
                    "result_confirmed": True,
                    "work_type": "service",
                    "field_code": "81111599",
                    "field_name": "정보시스템개발서비스",
                    "large_category": "ICT 서비스",
                    "middle_category": "SW 및 시스템 개발",
                    "classification_source": "procurement_classification",
                }
            ]

        async def competitors(self, catalog, **kwargs):
            return [
                {
                    "company_number": "2222222222",
                    "company_name": "경쟁사",
                    "bid_notice_id": "N1:000",
                    "participation_date": date(2025, 5, 1),
                    "participation_event_id": "N1:000:0:0",
                    "work_type": "service",
                    "field_code": "81111599",
                    "field_name": "정보시스템개발서비스",
                    "large_category": "ICT 서비스",
                    "middle_category": "SW 및 시스템 개발",
                    "classification_source": "procurement_classification",
                }
            ]

    inputs = {
        "business_registration_number": "1111111111",
        "period_from_year": 2025,
        "period_to_year": 2025,
        "work_type": "service",
        "large_category": "ICT 서비스",
        "page": 1,
        "page_size": 20,
    }
    catalog = RegistryLoader(REGISTRIES).load()
    history = await execute_company_participation_search(
        catalog,
        "search_bid_participations",
        inputs,
        reader=Reader(),
    )
    assert history.outcome["items"][0]["result"] == "unsuccessful"
    assert history.outcome["items"][0]["participant_count"] == 7
    competitors = await execute_company_competitor_analysis(
        catalog,
        "analyze_company_competitors",
        inputs,
        reader=Reader(),
    )
    assert competitors.outcome["items"][0]["co_participation_count"] == 1


@pytest.mark.asyncio
async def test_bid_notice_participations_reports_stored_completeness() -> None:
    class Reader:
        async def find(self, catalog, **kwargs):
            assert kwargs == {"notice_number": "R26TEST", "notice_order": "000"}
            return [
                {
                    "bid_notice_id": "R26TEST:000",
                    "notice_name": "테스트 공고",
                    "bid_classification_number": "1",
                    "rebid_number": "000",
                    "source_participant_count": 2,
                    "winner_business_registration_number": "1111111111",
                    "participation_id": "P1",
                    "business_registration_number": "1111111111",
                    "participant_name": "낙찰사",
                    "opening_rank": 1,
                    "bid_amount": Decimal("90"),
                    "bid_rate": Decimal("90.1"),
                    "result": "award",
                    "result_confirmed": True,
                }
            ]

    catalog = RegistryLoader(REGISTRIES).load()
    result = await execute_bid_notice_participations(
        catalog,
        "get_bid_notice_participations",
        {"bid_notice_id": "R26TEST:000"},
        reader=Reader(),
    )
    event = result.outcome["opening_events"][0]
    assert event["source_participant_count"] == 2
    assert event["stored_participant_count"] == 1
    assert event["returned_participant_count"] == 1
    assert event["data_completeness"] == {
        "status": "partial",
        "missing_reasons": [
            "stored_participant_count_less_than_source_participant_count"
        ],
    }
    assert result.outcome["data_completeness"]["status"] == "partial"
