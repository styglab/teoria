from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.bid_context.bid_participation import (
    execute_bid_participation_context,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_bid_participation_context_uses_prepublication_contract_market() -> None:
    class Reader:
        async def bid_context(self, catalog, **kwargs):
            return (
                {
                    "notice_name": "현재 사업",
                    "organization_code": "ORG",
                    "organization_name": "기관",
                    "notice_published_date": date(2026, 7, 1),
                    "work_type": "service",
                    "field_code": "81111599",
                    "large_category": "ICT 서비스",
                    "middle_category": "SW 및 시스템 개발",
                    "allocated_budget": Decimal("1000"),
                    "estimated_price": Decimal("900"),
                    "base_amount": None,
                },
                [],
            )

        async def activities(self, catalog, **kwargs):
            common = {
                "organization_code": "ORG",
                "organization_name": "기관",
                "procurement_classification_number": "81111599",
                "procurement_classification_name": "정보시스템개발서비스",
                "procurement_large_classification_name": "ICT 서비스",
                "procurement_middle_classification_name": "SW 및 시스템 개발",
                "purchase_items": None,
                "work_type": "service",
                "attribution_date_basis": "notice_published_at",
                "contract_version_count": 1,
                "contract_version_dates": [],
                "result_confirmed": True,
                "participation_successful": True,
            }
            return [
                {
                    **common,
                    "activity_type": "contract",
                    "event_key": "C1",
                    "bid_notice_id": "OLD1:000",
                    "notice_name": "과거 사업",
                    "company_number": "1111111111",
                    "company_name": "A사",
                    "activity_date": date(2026, 3, 1),
                    "notice_published_date": date(2026, 3, 1),
                    "event_amount": Decimal("500"),
                    "attributed_contract_amount": Decimal("500"),
                    "amount_completeness": "complete",
                    "first_contract_date": date(2026, 4, 1),
                    "latest_contract_version_date": date(2026, 4, 1),
                },
                {
                    **common,
                    "activity_type": "award",
                    "event_key": "A1",
                    "bid_notice_id": "OLD1:000",
                    "notice_name": "과거 사업",
                    "company_number": "1111111111",
                    "company_name": "A사",
                    "activity_date": date(2026, 3, 1),
                    "notice_published_date": date(2026, 3, 1),
                    "event_amount": Decimal("480"),
                    "attributed_contract_amount": None,
                    "amount_completeness": "unknown",
                    "first_contract_date": None,
                    "latest_contract_version_date": None,
                },
            ]

        async def notice_publications(self, catalog, **kwargs):
            return [
                {
                    "bid_notice_id": "OLD1:000",
                    "notice_name": "과거 사업",
                    "notice_published_date": date(2026, 3, 1),
                    "allocated_budget": Decimal("500"),
                    "estimated_price": Decimal("450"),
                    "base_amount": None,
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "purchase_items": None,
                    "work_type": "service",
                }
            ]

        async def bid_competition(self, catalog, **kwargs):
            return [
                {
                    "participant_count": 8,
                    "notice_published_date": date(2026, 3, 1),
                    "procurement_classification_number": "81111599",
                    "procurement_classification_name": "정보시스템개발서비스",
                    "procurement_large_classification_name": "ICT 서비스",
                    "procurement_middle_classification_name": "SW 및 시스템 개발",
                    "purchase_items": None,
                    "work_type": "service",
                }
            ]

        async def peer_field_market(self, catalog, **kwargs):
            contracts = []
            for organization, multiplier in (("ORG", 1), ("PEER", 2)):
                for index in range(10):
                    contracts.append(
                        {
                            "organization_code": organization,
                            "event_key": f"{organization}-{index}",
                            "first_contract_date": date(2026, 1, index + 1),
                            "company_number": f"{multiplier}{index % 5:09d}",
                            "company_name": f"업체 {index % 5}",
                            "attributed_contract_amount": Decimal("500")
                            if organization == "ORG"
                            else Decimal("250"),
                            "amount_completeness": "complete",
                        }
                    )
            competition = [
                {
                    "organization_code": organization,
                    "competition_event_id": f"{organization}-{index}",
                    "participant_count": count,
                }
                for organization, count in (("ORG", 8), ("PEER", 4))
                for index in range(5)
            ]
            return contracts, competition

    result = await execute_bid_participation_context(
        RegistryLoader(REGISTRIES).load(),
        "analyze_bid_participation_context",
        {"bid_notice_id": "CURRENT:000", "period_years": 3},
        reader=Reader(),
    )
    assert result.outcome["analysis_basis"]["period_to"] == date(2026, 6, 30)
    assert result.outcome["market_entry"]["new_supplier_company_count"] == 1
    assert result.outcome["supplier_concentration"]["top_1_share"] == 0.2
    assert (
        result.outcome["project_scale"]["current_project_amount_basis"]
        == "allocated_budget"
    )
    assert result.outcome["competition"]["overall_average_participant_count"] == 8
    assert (
        result.outcome["related_past_projects"][0]["relationship_type"] == "same_field"
    )
    benchmark = result.outcome["peer_benchmark"]
    assert benchmark["supplier_concentration"]["minimum_sample_satisfied"] is True
    assert benchmark["supplier_concentration"]["percentile_method"] == "midrank"
    assert (
        benchmark["supplier_concentration"]["current_value"]
        == result.outcome["supplier_concentration"]["top_5_share"]
    )
    assert benchmark["competition"]["participant_count_median"]["current_value"] == 8
    cases = result.outcome["new_supplier_similar_amount_cases"]
    assert cases["amount_range"]["minimum_amount"] == 500
    assert cases["amount_range"]["maximum_amount"] == 2000
    assert cases["case_unit"] == "contract_event"
    assert result.outcome["reconciliation"]["amount_difference"] == 0
