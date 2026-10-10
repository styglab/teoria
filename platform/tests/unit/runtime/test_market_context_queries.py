from teoria.runtime.market_context.queries.outcomes import (
    _PROCUREMENT_ACTIVITY_CONTRACTS_QUERY,
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
)
from teoria.runtime.market_context.queries.profiles import (
    _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
)


def test_procurement_outcome_awards_scopes_before_lineage_lookup() -> None:
    normalized = " ".join(_PROCUREMENT_OUTCOME_AWARDS_QUERY.split())

    assert "WITH scoped_awards AS MATERIALIZED" in normalized
    assert "FROM scoped_awards a LEFT JOIN LATERAL" in normalized
    assert (
        "WHERE n.notice_number=a.notice_number "
        "AND n.notice_order=a.notice_order LIMIT 1"
    ) in normalized


def test_procurement_profile_contracts_use_first_contract_date_cohort() -> None:
    normalized = " ".join(_PROCUREMENT_PROFILE_ACTIVITIES_QUERY.split())

    assert "c.first_contract_date AS activity_date" in normalized
    assert "'first_contract_date'::text AS attribution_date_basis" in normalized
    assert "COALESCE(n.notice_published_at::date,c.first_contract_date)" not in normalized
    assert "v.concluded_date DESC NULLS LAST" in normalized
    assert "c.first_contract_date IS NULL" in normalized


def test_procurement_profile_awards_use_award_or_opening_date_cohort() -> None:
    normalized = " ".join(_PROCUREMENT_PROFILE_ACTIVITIES_QUERY.split())

    award_date = "COALESCE(a.final_award_date,a.opening_at::date)"
    assert f"{award_date} AS activity_date" in normalized
    assert "'final_award_date_or_opening_at'::text AS attribution_date_basis" in normalized
    assert f"{award_date} >= %(period_from)s" in normalized
    assert f"{award_date} < %(period_to)s" in normalized


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
