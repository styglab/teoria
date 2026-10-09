from teoria.runtime.market_context.queries.outcomes import (
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
