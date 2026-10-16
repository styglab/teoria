from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.contracts.project_lineage import (
    execute_bid_project_lineage,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


class SimilarNoticeReader:
    async def find(self, catalog, bid_notice_id, *, period_years, result_statuses):
        assert period_years == 5
        assert result_statuses == ["awarded", "contracted"]
        notice = {
            "bid_notice_id": bid_notice_id,
            "notice_name": "정보시스템 구축 및 유지관리 사업",
            "notice_published_date": date(2026, 9, 1),
            "work_type": "service",
            "contract_method_name": "일반경쟁",
            "estimated_price": Decimal("200000000"),
            "allocated_budget": None,
            "demand_organization_code": "ORG-1",
            "demand_organization_name": "기관",
            "industry_codes": ["1468", "0036"],
            "industries": [
                {"industry_code": "1468", "industry_name": "소프트웨어사업자"},
                {"industry_code": "0036", "industry_name": "정보통신공사업"},
            ],
            "as_of": datetime(2026, 9, 23, tzinfo=timezone.utc),
        }
        rows = [
            {
                "bid_notice_id": "R25SIMILAR:000",
                "notice_number": "R25SIMILAR",
                "notice_order": "000",
                "notice_name": "정보시스템 구축 및 유지관리",
                "notice_published_date": date(2025, 7, 15),
                "work_type": "service",
                "contract_method_name": "일반경쟁",
                "estimated_price": Decimal("190000000"),
                "allocated_budget": None,
                "demand_organization_code": "ORG-2",
                "demand_organization_name": "과거기관",
                "industry_codes": ["1468", "0036"],
                "title_trigram_score": Decimal("0.9"),
                "winner_business_registration_number": "1234567890",
                "winner_name": "스마트이앤씨",
                "winning_amount": Decimal("170000000"),
                "winning_rate": Decimal("89.5"),
                "award_date": date(2025, 8, 1),
            },
            {
                "bid_notice_id": "R24ORGFIELD:000",
                "notice_number": "R24ORGFIELD",
                "notice_order": "000",
                "notice_name": "소득기반 정보시스템 개선 사업",
                "notice_published_date": date(2024, 5, 10),
                "work_type": "service",
                "contract_method_name": "제한경쟁",
                "estimated_price": Decimal("700000000"),
                "allocated_budget": None,
                "demand_organization_code": "ORG-1",
                "demand_organization_name": "기관",
                "industry_codes": ["1468"],
                "title_trigram_score": Decimal("0.1"),
                "winner_business_registration_number": "9876543210",
                "winner_name": "과거업체",
                "winning_amount": Decimal("650000000"),
                "winning_rate": Decimal("92.0"),
                "award_date": date(2024, 6, 1),
            },
        ]
        return notice, rows


@pytest.mark.asyncio
async def test_project_lineage_keeps_structured_only_matches_as_candidates() -> None:
    result = await execute_bid_project_lineage(
        RegistryLoader(REGISTRIES).load(),
        "find_bid_project_lineage",
        {"bid_notice_id": "R26TEST:000", "period_years": 5},
        reader=SimilarNoticeReader(),
    )

    assert result.outcome["items"]
    assert all(
        item["relationship_type"] == "related_candidate"
        for item in result.outcome["items"]
    )
    assert all(
        item["confirmation_status"] == "requires_source_evidence"
        for item in result.outcome["items"]
    )
    assert result.outcome["policy"]["title_similarity_alone_confirms_lineage"] is False
