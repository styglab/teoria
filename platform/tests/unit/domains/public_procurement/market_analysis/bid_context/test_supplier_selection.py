from datetime import date
from decimal import Decimal
from pathlib import Path

from teoria.domains.public_procurement.market_analysis.bid_context.supplier_selection import (
    build_attention_suppliers as _build_attention_suppliers,
)
from teoria.domains.public_procurement.market_analysis.bid_context.supplier_selection import (
    contract_time_relationship as _contract_time_relationship,
)

REGISTRIES = Path(__file__).parents[6] / "registries"


def test_contract_time_relationship_excludes_same_day_and_future_contracts() -> None:
    dates = [date(2026, 7, 14), date(2026, 8, 6), date(2026, 8, 6)]
    first = _contract_time_relationship(date(2026, 7, 14), dates)
    later = _contract_time_relationship(date(2026, 8, 6), dates)
    assert first["contract_time_relationship_status"] == "entry_or_reentering"
    assert first["prior_same_organization_field_contract_count"] == 0
    assert later["contract_time_relationship_status"] == "repeat"
    assert later["prior_same_organization_field_contract_count"] == 1
    assert later["history_period_to"] == date(2026, 8, 5)



def test_attention_suppliers_detects_entry_then_repeat() -> None:
    rows = [{"event_key": "ENTRY", "unified_contract_number": "U1",
             "contract_name": "첫 계약", "first_contract_date": date(2026, 7, 14),
             "contract_amount": Decimal("80"), "attributed_contract_amount": Decimal("80"),
             "company_number": "1048188364", "company_name": "웨슬리퀘스트"},
            {"event_key": "REPEAT", "unified_contract_number": "U2",
             "contract_name": "후속 계약", "first_contract_date": date(2026, 8, 6),
             "contract_amount": Decimal("241"), "attributed_contract_amount": Decimal("241"),
             "company_number": "1048188364", "company_name": "웨슬리퀘스트"}]
    result, basis = _build_attention_suppliers(rows,
        history={"1048188364": [date(2026, 7, 14), date(2026, 8, 6)]},
        cutoff=date(2026, 9, 4), period_from=date(2023, 9, 4),
        filters={"work_type": "service", "large_category": "ICT 서비스",
                 "middle_category": "SW 및 시스템 개발", "field_code": "81111599"},
        organization_code="Z004905", reference_amount=Decimal("200"))
    supplier = result[0]
    assert "entry_then_repeat" in supplier["attention_reasons"]
    assert "large_contract_experience" not in supplier["attention_reasons"]
    assert "field_upper_quartile_experience" in supplier["attention_reasons"]
    assert supplier["display_attention_reasons"] == [
        "similar_amount_experience", "contract_amount_leader"]
    assert supplier["attention_reason_evidence"]["entry_then_repeat"]["days_to_repeat"] == 23
    assert supplier["first_contract_status"] == "entry_or_reentering"
    assert basis["selection_method"] == (
        "distinct_reason_representatives_then_quota_fill_and_priority_sort")
    assert basis["sort_priority"][:2] == [
        "similar_amount_experience", "contract_amount_leader"]

