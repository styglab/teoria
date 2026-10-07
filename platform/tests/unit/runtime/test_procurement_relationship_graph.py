from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError
from teoria.runtime.market_context.relationship_graph import (
    execute_procurement_relationship_graph_entities,
    execute_procurement_relationship_graph_summary,
)


REGISTRIES = Path(__file__).parents[3] / "registries"
VERSION = datetime(2026, 10, 7, 3, tzinfo=timezone.utc)


class SummaryReader:
    def overview(self, _catalog: Any, **parameters: Any):
        assert parameters["group_by"] == "field"
        return (
            {"graph_version": VERSION},
            [{
                "cluster_id": "service:81112002", "work_type": "service",
                "field_code": "81112002", "field_name": "정보시스템 유지관리",
                "organization_count": 12, "company_count": 48,
                "link_count": 93, "contract_count": 426,
                "total_attributed_contract_amount": 128_400_000_000,
            }],
            {"organization_count": 12, "company_count": 48, "link_count": 93},
        )


class EntityReader:
    def __init__(self) -> None:
        self.after_values: list[str | None] = []

    def entities(self, _catalog: Any, **parameters: Any):
        self.after_values.append(parameters["after_company_number"])
        company = "1111111111" if not parameters["after_company_number"] else "2222222222"
        return (
            {"graph_version": VERSION},
            [
                {
                    "id": f"company:{company}", "type": "procurement_supplier",
                    "business_registration_number": company, "company_name": "업체",
                },
                {
                    "id": "organization:O1", "type": "public_organization",
                    "organization_code": "O1", "organization_name": "기관",
                },
            ],
            [{
                "organization_code": "O1", "company_number": company,
                "contract_count": 3, "total_attributed_contract_amount": 100,
                "known_amount_count": 3, "amount_completeness": "complete",
                "first_contract_date": date(2022, 1, 1),
                "latest_contract_date": date(2026, 1, 1),
                "company_roles": ["단독"],
            }],
            {"organization_count": 12, "company_count": 48, "link_count": 93},
            not parameters["after_company_number"],
        )


@pytest.mark.asyncio
async def test_summary_returns_pinned_graph_version_and_cluster_totals() -> None:
    result = await execute_procurement_relationship_graph_summary(
        RegistryLoader(REGISTRIES).load(),
        "summarize_procurement_relationship_graph",
        {
            "group_by": "field", "period_from_year": 2022, "period_to_year": 2026,
        },
        reader=SummaryReader(),
    )

    assert result.outcome["graph_version"] == "2026-10-07T03:00:00+00:00"
    assert result.outcome["total_nodes"] == 60
    assert result.outcome["total_links"] == 93
    assert result.outcome["clusters"][0]["cluster_id"] == "service:81112002"


@pytest.mark.asyncio
async def test_entity_cursor_pins_version_cluster_and_period() -> None:
    reader = EntityReader()
    inputs = {
        "graph_version": "2026-10-07T03:00:00Z",
        "cluster_id": "service:81112002",
        "period_from_year": 2022, "period_to_year": 2026,
        "page_size": 1,
    }
    first = await execute_procurement_relationship_graph_entities(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_relationship_graph_entities", inputs, reader=reader,
    )
    assert first.outcome["truncated"] is True
    assert first.outcome["next_cursor"]
    assert first.outcome["returned_nodes"] == 2
    assert first.outcome["returned_links"] == 1

    second = await execute_procurement_relationship_graph_entities(
        RegistryLoader(REGISTRIES).load(),
        "search_procurement_relationship_graph_entities",
        {
            **inputs,
            "graph_version": first.outcome["graph_version"],
            "cursor": first.outcome["next_cursor"],
        },
        reader=reader,
    )
    assert reader.after_values == [None, "1111111111"]
    assert second.outcome["truncated"] is False

    with pytest.raises(CapabilityExecutionError, match="cursor does not match"):
        await execute_procurement_relationship_graph_entities(
            RegistryLoader(REGISTRIES).load(),
            "search_procurement_relationship_graph_entities",
            {**inputs, "cluster_id": "service:other", "cursor": first.outcome["next_cursor"]},
            reader=reader,
        )


@pytest.mark.asyncio
async def test_entity_search_rejects_inverted_period() -> None:
    with pytest.raises(CapabilityExecutionError, match="period_from_year"):
        await execute_procurement_relationship_graph_entities(
            RegistryLoader(REGISTRIES).load(),
            "search_procurement_relationship_graph_entities",
            {
                "graph_version": "2026-10-07T03:00:00+00:00",
                "cluster_id": "service:81112002",
                "period_from_year": 2026,
                "period_to_year": 2022,
            },
            reader=EntityReader(),
        )
