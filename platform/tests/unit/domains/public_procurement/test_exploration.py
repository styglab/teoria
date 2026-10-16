from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from teoria.domains.public_procurement.exploration.discovery import (
    execute_autocomplete_procurement_entities,
    execute_procurement_classification_catalog,
    execute_procurement_region_filter_options,
)
from teoria.domains.public_procurement.exploration.field_market import (
    execute_procurement_field_market,
)
from teoria.domains.public_procurement.exploration.network import (
    execute_procurement_network,
)


CATALOG = SimpleNamespace(release=None)
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class Reader:
    async def autocomplete(self, catalog, **kwargs):
        return [
            {
                "entity_type": "bid_notice",
                "entity_id": "R25BK:00",
                "display_name": "정보시스템 유지관리",
                "display_number": "R25BK",
                "sort_at": NOW,
                "context": {
                    "work_type": "service",
                    "field_code": "81111811",
                    "region_basis": "participation_restriction",
                    "region_code": "11",
                    "region_codes": ["11"],
                    "region_conditions": [{"code": "11", "name": "서울특별시"}],
                },
            }
        ]

    async def classifications(self, catalog, **kwargs):
        return (
            [
                {
                    "field_code": "81111811",
                    "field_name": "정보시스템 유지관리서비스",
                    "large_category": "서비스",
                    "middle_category": "정보기술서비스",
                    "work_types": ["service"],
                    "observed_notice_count": 3,
                    "updated_at": NOW,
                }
            ],
            False,
            NOW,
        )

    async def regions(self, catalog, **kwargs):
        return (
            [
                {
                    "region_code": "11",
                    "region_name": "서울특별시",
                    "observed_notice_count": 2,
                    "updated_at": NOW,
                }
            ],
            NOW,
        )

    async def network_edges(self, catalog, **kwargs):
        row = {
            "organization_code": "ORG",
            "organization_name": "기관",
            "company_number": "1234567890",
            "company_name": "업체",
            "contract_count": 2,
            "attributed_amount": Decimal("1000"),
            "first_contract_date": NOW.date(),
            "latest_contract_date": NOW.date(),
            "amount_completeness": "complete",
            "updated_at": NOW,
        }
        return [row], [], NOW

    async def field_market(self, catalog, **kwargs):
        return (
            [
                {
                    "year": 2026,
                    "field_name": "정보시스템 유지관리서비스",
                    "large_category": "서비스",
                    "middle_category": "정보기술서비스",
                    "organization_count": 1,
                    "company_count": 1,
                    "contract_count": 2,
                    "total_attributed_contract_amount": Decimal("1000"),
                    "missing_attributed_amount_count": 0,
                    "updated_at": NOW,
                }
            ],
            NOW,
        )


@pytest.mark.asyncio
async def test_autocomplete_returns_filter_readiness() -> None:
    result = await execute_autocomplete_procurement_entities(
        CATALOG,
        "autocomplete_procurement_entities",
        {"query": "유지관리"},
        reader=Reader(),
    )
    candidate = result.outcome["candidates"][0]
    assert candidate["applicable_filters"] == ["work_type", "field_code", "region"]
    assert candidate["missing_filters"] == []
    assert candidate["filter_values"]["region"] == {
        "basis": "participation_restriction",
        "codes": ["11"],
        "match": "any",
    }


@pytest.mark.asyncio
async def test_catalog_and_region_options_preserve_basis() -> None:
    catalog = await execute_procurement_classification_catalog(
        CATALOG,
        "get_procurement_classification_catalog",
        {},
        reader=Reader(),
    )
    regions = await execute_procurement_region_filter_options(
        CATALOG,
        "get_procurement_region_filter_options",
        {},
        reader=Reader(),
    )
    assert catalog.outcome["items"][0]["field_code"] == "81111811"
    assert regions.outcome["region_basis"] == "participation_restriction"


@pytest.mark.asyncio
async def test_network_keeps_relationship_kinds_separate() -> None:
    result = await execute_procurement_network(
        CATALOG,
        "get_procurement_network",
        {
            "root_type": "organization",
            "root_id": "ORG",
            "region_codes": ["11", "41"],
            "period_from_year": 2024,
            "period_to_year": 2026,
        },
        reader=Reader(),
    )
    relationships = result.outcome["edges"][0]["relationships"]
    assert relationships["contract"]["event_count"] == 2
    assert relationships["observed_participation"] is None
    assert result.outcome["coverage"]["observed_participation"] == "not_in_read_model"
    assert (
        result.outcome["analysis_basis"]["region_basis"] == "participation_restriction"
    )
    assert result.outcome["analysis_basis"]["region_code"] is None
    assert result.outcome["analysis_basis"]["region_codes"] == ["11", "41"]


@pytest.mark.asyncio
async def test_field_market_states_collection_scope() -> None:
    result = await execute_procurement_field_market(
        CATALOG,
        "analyze_procurement_field_market",
        {
            "field_code": "81111811",
            "period_from_year": 2024,
            "period_to_year": 2026,
            "region_basis": "participation_restriction",
            "region_code": "11",
        },
        reader=Reader(),
    )
    assert result.outcome["summary"]["contract_count"] == 2
    assert result.outcome["coverage"]["is_full_market"] is False
    assert (
        result.outcome["coverage"]["region_filter"]
        == "linked_structured_bid_notice_restriction"
    )
