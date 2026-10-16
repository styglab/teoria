from teoria.domains.public_procurement.market_analysis.activity.sql import (
    _PROCUREMENT_ACTIVITY_CONTRACTS_QUERY,
)


def test_procurement_activity_contracts_use_profile_contract_event_cohort() -> None:
    normalized = " ".join(_PROCUREMENT_ACTIVITY_CONTRACTS_QUERY.split())

    assert "COALESCE(NULLIF(c.confirmed_contract_number,'')" in normalized
    assert "NULLIF(c.contract_reference_number,''),c.unified_contract_number" in normalized
    assert "min(concluded_date) AS first_contract_date" in normalized
    assert "DISTINCT ON (v.organization_code,v.contract_event_key)" in normalized
    assert "c.first_contract_date >= %(period_from)s" in normalized
    assert "c.first_contract_date < %(period_to)s" in normalized
    assert "AS procurement_classification_number" in normalized
    assert "AS procurement_classification_name" in normalized
    assert "n.procurement_large_classification_name" in normalized
    assert "n.purchase_items" in normalized
    assert (
        "c.confirmed_contract_number,c.contract_reference_number,c.contract_name"
        in normalized
    )
    assert "c.long_term_continuation_type,c.normalized_notice_number" in normalized
    assert "c.request_number,c.contract_detail_url" in normalized
    assert "c.current_contract_amount_currency,c.total_amount" in normalized
    assert "c.total_amount_currency,c.is_joint_contract" in normalized

