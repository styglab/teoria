from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.outcomes.service import (
    execute_procurement_outcome_search,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_procurement_outcome_search_merges_awards_contracts_and_paginates() -> (
    None
):
    class Reader:
        async def find(self, catalog, *, organization_code, period_from, period_to):
            assert organization_code == "ORG-1"
            assert period_from == date(2025, 1, 1)
            assert period_to == date(2026, 1, 1)
            classification = {
                "work_type": "service",
                "field_code": "81111599",
                "field_name": "정보시스템개발서비스",
                "large_category": "ICT 서비스",
                "middle_category": "SW 및 시스템 개발",
            }
            awards = [
                {
                    "award_id": "N1:000:0:0",
                    "bid_notice_id": "N1:000",
                    "bid_classification_number": "0",
                    "rebid_number": "0",
                    "notice_name": "정보시스템 구축",
                    "organization_name": "기관",
                    "award_date": date(2025, 3, 1),
                    "winner_name": "낙찰사",
                    "winner_business_registration_number": "1111111111",
                    "winning_amount": Decimal("90"),
                    "winning_rate": Decimal("87.4"),
                    **classification,
                },
                {
                    "award_id": "N2:000:0:0",
                    "bid_notice_id": "N2:000",
                    "bid_classification_number": "0",
                    "rebid_number": "0",
                    "notice_name": "정보시스템 운영",
                    "organization_name": "기관",
                    "award_date": date(2025, 5, 1),
                    "winner_name": "낙찰전용",
                    "winner_business_registration_number": "2222222222",
                    "winning_amount": Decimal("80"),
                    "winning_rate": None,
                    **classification,
                },
            ]
            contracts = []
            for unified_number, contract_date, amount in (
                ("C1-OLD", date(2024, 4, 1), Decimal("95")),
                ("C1-NEW", date(2025, 4, 1), Decimal("100")),
            ):
                for sequence, number, name, role, share in (
                    (1, "1111111111", "대표사", "주계약업체", Decimal("60")),
                    (2, "3333333333", "구성사", "도급업체", Decimal("40")),
                ):
                    contracts.append(
                        {
                            "contract_event_id": "ROOT-C1",
                            "unified_contract_number": unified_number,
                            "bid_notice_id": "N1:000",
                            "notice_name": "정보시스템 구축",
                            "organization_name": "기관",
                            "contract_date": contract_date,
                            "contract_amount": amount,
                            "is_joint_contract": True,
                            "supplier_sequence": sequence,
                            "business_registration_number": number,
                            "supplier_name": name,
                            "supplier_role_name": role,
                            "participation_share_rate": share,
                            **classification,
                        }
                    )
            return awards, contracts

    result = await execute_procurement_outcome_search(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_outcomes",
        {
            "organization_code": "ORG-1",
            "period_from_year": 2025,
            "period_to_year": 2025,
            "work_type": "service",
            "large_category": "ICT 서비스",
            "query": "정보시스템",
            "page": 1,
            "page_size": 20,
        },
        reader=Reader(),
    )

    assert result.outcome["pagination"]["total_items"] == 2
    by_id = {item["outcome_id"]: item for item in result.outcome["items"]}
    assert by_id["N1:000"]["stage"] == "contract"
    assert by_id["N1:000"]["latest_activity_date"] == date(2025, 4, 1)
    assert by_id["N1:000"]["contract"]["contract_version_count"] == 2
    assert by_id["N1:000"]["contract"]["contract_amount"] == 100
    assert by_id["N1:000"]["contract"]["lead_contractor"]["company_name"] == "대표사"
    assert by_id["N1:000"]["contract"]["contractor_count"] == 2
    assert len(by_id["N1:000"]["contracts"]) == 1
    assert len(by_id["N1:000"]["awards"]) == 1
    assert by_id["N2:000"]["stage"] == "award"
    assert len(result.objects) == 2
