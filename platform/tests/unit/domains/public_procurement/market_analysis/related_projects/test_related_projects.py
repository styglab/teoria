from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.related_projects.search import (
    execute_bid_related_projects_search,
)
from teoria.domains.public_procurement.market_analysis.related_projects.similar_experience import (
    execute_company_similar_project_experience,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_related_projects_pages_by_contract_event_and_nests_contractors() -> None:
    class Reader:
        async def bid_context(self, catalog, **kwargs):
            return (
                {
                    "notice_name": "현재 사업",
                    "organization_code": "ORG",
                    "organization_name": "기관",
                    "notice_published_date": date(2026, 9, 1),
                    "work_type": "service",
                    "field_code": "81111599",
                    "large_category": "ICT 서비스",
                    "middle_category": "SW 및 시스템 개발",
                    "allocated_budget": Decimal("650"),
                },
                [],
            )

        async def peer_field_contracts(self, catalog, **kwargs):
            base = {
                "organization_code": "ORG",
                "organization_name": "기관",
                "work_type": "service",
                "field_code": "81111599",
                "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
                "amount_completeness": "complete",
                "latest_contract_version_date": date(2026, 6, 1),
                "contract_version_count": 1,
                "normalized_notice_number": None,
                "company_role": "공동수급",
                "share_percent": 50,
            }
            return [
                {
                    **base,
                    "event_key": "OLD-A",
                    "unified_contract_number": "OLD-A",
                    "contract_name": "과거 A",
                    "first_contract_date": date(2024, 1, 1),
                    "company_number": "A",
                    "company_name": "A사",
                    "contract_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                },
                {
                    **base,
                    "event_key": "OLD-B",
                    "unified_contract_number": "OLD-B",
                    "contract_name": "과거 B",
                    "first_contract_date": date(2024, 1, 1),
                    "company_number": "B",
                    "company_name": "B사",
                    "contract_amount": Decimal("100"),
                    "attributed_contract_amount": Decimal("100"),
                },
                {
                    **base,
                    "event_key": "JOINT",
                    "unified_contract_number": "JOINT-1",
                    "contract_name": "공동 계약",
                    "first_contract_date": date(2026, 6, 1),
                    "company_number": "A",
                    "company_name": "A사",
                    "contract_amount": Decimal("650"),
                    "attributed_contract_amount": Decimal("331.5"),
                },
                {
                    **base,
                    "event_key": "JOINT",
                    "unified_contract_number": "JOINT-1",
                    "contract_name": "공동 계약",
                    "first_contract_date": date(2026, 6, 1),
                    "company_number": "B",
                    "company_name": "B사",
                    "contract_amount": Decimal("650"),
                    "attributed_contract_amount": Decimal("318.5"),
                },
            ]

    result = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(),
        "search_bid_related_projects",
        {
            "bid_notice_id": "CURRENT:000",
            "project_filters": ["repeat_supplier"],
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    joint = next(
        item for item in result.outcome["items"] if item["contract_event_id"] == "JOINT"
    )
    assert joint["contractor_count"] == 2
    assert joint["relationship_status_summary"] == "repeat"
    assert joint["contractor_amount_completeness"] == "complete"
    assert joint["contractor_attributed_amount_sum"] == 650
    assert result.outcome["pagination"]["total_items"] == 1
    assert result.outcome["filter_counts"]["repeat_supplier"] == 1

    combined = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(),
        "search_bid_related_projects",
        {
            "bid_notice_id": "CURRENT:000",
            "project_filters": ["similar_amount", "entry_or_reentering_supplier"],
            "filter_operator": "and",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    assert combined.outcome["items"] == []
    assert combined.outcome["pagination"]["total_items"] == 0
    assert combined.outcome["applied_filter"] == {
        "filters": ["similar_amount", "entry_or_reentering_supplier"],
        "operator": "and",
        "total_items": 0,
    }
    assert combined.outcome["filter_counts"] == {
        "all": 3,
        "similar_amount": 1,
        "entry_or_reentering_supplier": 2,
        "repeat_supplier": 1,
    }

    either = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(),
        "search_bid_related_projects",
        {
            "bid_notice_id": "CURRENT:000",
            "project_filters": ["similar_amount", "entry_or_reentering_supplier"],
            "filter_operator": "or",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    assert either.outcome["pagination"]["total_items"] == 3
    assert len({item["contract_event_id"] for item in either.outcome["items"]}) == 3

    unfiltered = await execute_bid_related_projects_search(
        RegistryLoader(REGISTRIES).load(),
        "search_bid_related_projects",
        {
            "bid_notice_id": "CURRENT:000",
            "project_filters": [],
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )
    assert unfiltered.outcome["pagination"]["total_items"] == 3
    assert unfiltered.outcome["applied_filter"]["filters"] == []


@pytest.mark.asyncio
async def test_company_similar_project_experience_uses_any_industry_overlap() -> None:
    class Reader:
        async def find(self, catalog, **kwargs):
            return (
                {
                    "notice_name": "정보시스템 구축 및 운영 사업",
                    "work_type": "service",
                    "estimated_price": Decimal("200000000"),
                    "allocated_budget": None,
                    "industry_codes": ["0036", "1468"],
                    "industry_names": {
                        "0036": "정보통신공사업",
                        "1468": "소프트웨어사업자",
                    },
                },
                [
                    {
                        "bid_notice_id": "R25ONE:000",
                        "notice_name": "전산장비 운영 용역",
                        "notice_published_date": date(2025, 1, 1),
                        "demand_organization_code": "ORG-2",
                        "demand_organization_name": "다른기관",
                        "work_type": "service",
                        "estimated_price": Decimal("180000000"),
                        "allocated_budget": None,
                        "industry_codes": ["1468"],
                        "award_date": date(2025, 2, 1),
                        "winning_amount": Decimal("170000000"),
                        "contract_date": None,
                        "contract_amount": None,
                        "participation_share_rate": None,
                        "supplier_role_name": None,
                        "supplier_count": 0,
                    }
                ],
            )

    result = await execute_company_similar_project_experience(
        RegistryLoader(REGISTRIES).load(),
        "get_company_similar_project_experience",
        {
            "reference_bid_notice_id": "R26TEST:000",
            "business_registration_number": "1234567890",
            "period_years": 10,
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assessment = result.outcome["experiences"][0]["industry_license_assessment"]
    assert assessment["matched_codes"] == ["1468"]
    assert assessment["coverage_ratio"] == 0.5
    assert assessment["all_required_codes_included"] is False
    assert result.outcome["analysis_basis"]["title_keyword_filter_applied"] is False
    assert result.outcome["summary"]["candidate_count"] == 1
    assert result.outcome["summary"]["event_count"] == 1
    assert result.outcome["summary"]["limited_event_count"] == 1
    assert result.objects[0].object_type == "company_similar_project_experience"
