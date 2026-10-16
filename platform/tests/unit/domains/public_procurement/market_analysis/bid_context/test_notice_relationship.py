from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from teoria.domains.public_procurement.market_analysis.bid_context.notice_relationship import (
    execute_bid_notice_relationship_context,
)
from teoria.registry.loader import RegistryLoader

REGISTRIES = Path(__file__).parents[6] / "registries"


@pytest.mark.asyncio
async def test_bid_relationship_context_batches_only_history_before_notice() -> None:
    class Reader:
        observed_period_to = None

        async def bid_context(self, catalog, **kwargs):
            return (
                {
                    "notice_name": "현재 공고",
                    "organization_code": "ORG-1",
                    "organization_name": "기관",
                    "notice_published_date": date(2026, 4, 1),
                },
                [
                    {
                        "company_number": "1111111111",
                        "company_name": "업체",
                        "opening_rank": 1,
                        "bid_amount": Decimal("90"),
                        "bid_rate": Decimal("90"),
                        "award_date": date(2026, 5, 1),
                        "winning_amount": Decimal("90"),
                        "winning_rate": Decimal("90"),
                        "contract_date": None,
                        "contract_amount": None,
                        "attributed_contract_amount": None,
                        "share_percent": None,
                        "company_role": None,
                        "amount_completeness": None,
                    }
                ],
            )

        async def activities(self, catalog, **kwargs):
            self.observed_period_to = kwargs["period_to"]
            return []

    reader = Reader()
    result = await execute_bid_notice_relationship_context(
        RegistryLoader(REGISTRIES).load(),
        "get_bid_notice_relationship_context",
        {"bid_notice_id": "N2:000", "relationship_history_years": 5},
        reader=reader,
    )

    assert reader.observed_period_to == date(2026, 4, 1)
    assert result.outcome["analysis_basis"]["period_from"] == date(2022, 1, 1)
    assert result.outcome["analysis_basis"]["period_type"] == "calendar_fiscal_years"
    assert result.outcome["participants"][0]["result"] == "awarded"
    assert (
        result.outcome["participants"][0]["prior_organization_relationship"][
            "award_event_count"
        ]
        == 0
    )
