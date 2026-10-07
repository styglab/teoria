from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.runner import CapabilityExecutionError
from teoria.runtime.market_context.processor import execute_procurement_relationship_context


REGISTRIES = Path(__file__).parents[3] / "registries"


def _row(
    organization: str, company: str, event: str, amount: int | None, *,
    contract_amount: int | None = None, first_date: date = date(2024, 1, 1),
) -> dict[str, Any]:
    return {
        "organization_code": organization,
        "organization_name": f"기관 {organization}",
        "contract_event_id": event,
        "unified_contract_number": event,
        "first_contract_date": first_date,
        "latest_contract_version_date": first_date,
        "contract_version_count": 1,
        "company_number": company,
        "company_name": f"업체 {company}",
        "company_role": "단독" if amount is not None else "공동수급업체",
        "share_percent": 100 if amount is not None else None,
        "attributed_contract_amount": amount,
        "amount_completeness": "complete" if amount is not None else "partial",
        "contract_amount": contract_amount if contract_amount is not None else amount,
        "work_type": "service",
        "field_code": "81112002",
        "field_name": "소프트웨어 유지 및 지원",
        "large_category": "용역",
        "middle_category": "정보기술",
        "normalized_notice_number": None,
        "refreshed_at": datetime(2026, 10, 7, tzinfo=timezone.utc),
    }


class Reader:
    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def find(self, _catalog: Any, **parameters: Any) -> list[dict[str, Any]]:
        self.calls.append(parameters)
        return self.responses[len(self.calls) - 1]


@pytest.mark.asyncio
async def test_organization_seed_returns_two_hops_without_amount_fallback() -> None:
    first = [
        _row("O1", "1111111111", "E1", 100, contract_amount=100),
        _row("O1", "2222222222", "E2", None, contract_amount=900),
    ]
    second = first + [
        _row("O2", "1111111111", "E3", 50, contract_amount=50),
    ]
    reader = Reader([first, second])

    result = await execute_procurement_relationship_context(
        RegistryLoader(REGISTRIES).load(),
        "analyze_procurement_relationship_context",
        {
            "seed_type": "organization", "seed_id": "O1", "depth": 2,
            "period_from_year": 2022, "period_to_year": 2026,
            "work_type": "service", "large_category": "용역",
            "middle_category": "정보기술", "field_code": "81112002",
            "minimum_contract_count": 1, "minimum_contract_amount": 0,
            "sort": "contract_amount_desc", "max_organizations": 30,
            "max_companies": 50, "max_links": 200,
        },
        reader=reader,
    )

    assert len(reader.calls) == 2
    assert reader.calls[0]["organization_codes"] == ["O1"]
    assert reader.calls[1]["company_numbers"] == ["1111111111", "2222222222"]
    assert all(call["field_code"] == "81112002" for call in reader.calls)
    assert result.outcome["summary"] == {
        "organization_count": 2,
        "company_count": 2,
        "link_count": 3,
        "total_contract_count": 3,
        "total_contract_amount": 1050,
        "total_attributed_contract_amount": 150,
        "known_attributed_amount_contract_party_count": 2,
        "missing_attributed_amount_contract_party_count": 1,
        "amount_completeness": "partial",
    }
    missing_link = next(
        item for item in result.outcome["links"]
        if item["company_number"] == "2222222222"
    )
    assert missing_link["properties"]["total_attributed_contract_amount"] is None
    assert missing_link["properties"]["missing_amount_contract_count"] == 1
    assert missing_link["properties"]["relationship_status"] == "confirmed"
    assert missing_link["properties"]["depth_from_seed"] == 1
    assert {
        item["organization_code"]: item["depth_from_seed"]
        for item in result.outcome["organizations"]
    } == {"O1": 0, "O2": 2}
    assert result.outcome["truncated"] is False
    assert result.outcome["analysis_basis"]["company_amount_basis"] == (
        "attributed_contract_amount_without_fallback"
    )
    assert result.outcome["data_completeness"]["status"] == "partial"
    assert result.outcome["data_completeness"]["missing_reasons"] == [
        "some_contract_party_amounts_not_attributable"
    ]
    assert result.outcome["data_completeness"]["classification_scope_complete"] is True


@pytest.mark.asyncio
async def test_company_seed_applies_node_and_link_limits_with_reasons() -> None:
    first = [
        _row("O1", "1111111111", "E1", 100),
        _row("O2", "1111111111", "E2", 50),
    ]
    second = [
        _row("O1", "1111111111", "E1", 100),
        _row("O1", "2222222222", "E3", 80),
        _row("O1", "3333333333", "E4", 70),
    ]
    reader = Reader([first, second])

    result = await execute_procurement_relationship_context(
        RegistryLoader(REGISTRIES).load(),
        "analyze_procurement_relationship_context",
        {
            "seed_type": "company", "seed_id": "111-11-11111", "depth": 2,
            "period_from_year": 2022, "period_to_year": 2026,
            "minimum_contract_count": 1, "minimum_contract_amount": 0,
            "sort": "contract_amount_desc", "max_organizations": 1,
            "max_companies": 2, "max_links": 1,
        },
        reader=reader,
    )

    assert reader.calls[0]["company_numbers"] == ["1111111111"]
    assert reader.calls[1]["organization_codes"] == ["O1"]
    assert result.outcome["summary"]["link_count"] == 1
    assert result.outcome["summary"]["organization_count"] == 1
    assert result.outcome["summary"]["company_count"] == 1
    assert result.outcome["truncated"] is True
    assert set(result.outcome["truncation_reasons"]) == {
        "max_organizations", "max_companies", "max_links",
    }
    assert result.outcome["seed"] == {"type": "company", "id": "1111111111"}
    assert result.outcome["data_completeness"]["status"] == "partial"
    assert result.outcome["data_completeness"]["missing_reasons"] == [
        "unclassified_contracts_not_in_relationship_ledger"
    ]


@pytest.mark.asyncio
async def test_rejects_unsupported_depth() -> None:
    with pytest.raises(CapabilityExecutionError, match="depth must be 1 or 2"):
        await execute_procurement_relationship_context(
            RegistryLoader(REGISTRIES).load(),
            "analyze_procurement_relationship_context",
            {"seed_type": "organization", "seed_id": "O1", "depth": 3},
            reader=Reader([]),
        )
