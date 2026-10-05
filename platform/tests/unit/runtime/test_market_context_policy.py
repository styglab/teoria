from datetime import date
from decimal import Decimal

from teoria.runtime.market_context.attention import AttentionSupplierPolicy
from teoria.runtime.market_context.related_projects import (
    RelatedProjectQuery,
    filter_and_page_related_projects,
)


def _project(event_id: str, amount: int, matched: set[str]) -> dict:
    return {
        "contract_event_id": event_id,
        "contract_amount": amount,
        "contract_date": date(2026, 1, int(event_id[-1])),
        "matched_filters": {"same_field", *matched},
        "repeat_suppliers": ["company"] if "repeat_supplier" in matched else [],
    }


def test_attention_policy_exposes_business_priority_in_one_place() -> None:
    policy = AttentionSupplierPolicy()
    assert policy.reason_priority[:5] == (
        "similar_amount_experience",
        "contract_amount_leader",
        "entry_then_repeat",
        "repeat_contracts",
        "recent_contract",
    )
    assert policy.display_reason_limit == 2


def test_related_project_policy_filters_before_pagination() -> None:
    items = [
        _project("E1", 100, {"similar_amount"}),
        _project("E2", 200, {"entry_or_reentering_supplier"}),
        _project("E3", 300, {"similar_amount", "entry_or_reentering_supplier"}),
    ]
    query = RelatedProjectQuery(
        filters=("similar_amount", "entry_or_reentering_supplier"),
        filters_supplied=True, operator="and", page=1, page_size=1,
    )
    result = filter_and_page_related_projects(
        items, query, reference_amount=Decimal("250"))
    assert result["filter_counts"] == {
        "all": 3, "similar_amount": 2,
        "entry_or_reentering_supplier": 2, "repeat_supplier": 0,
    }
    assert result["pagination"]["total_items"] == 1
    assert result["items"][0]["contract_event_id"] == "E3"
