

from teoria.domains.public_procurement.market_analysis.profiles.sql import (
    _PROCUREMENT_PROFILE_ACTIVITIES_QUERY,
)


def test_procurement_profile_contracts_use_first_contract_date_cohort() -> None:
    normalized = " ".join(_PROCUREMENT_PROFILE_ACTIVITIES_QUERY.split())

    assert "c.first_contract_date AS activity_date" in normalized
    assert "'first_contract_date'::text AS attribution_date_basis" in normalized
    assert "COALESCE(n.notice_published_at::date,c.first_contract_date)" not in normalized
    assert "v.concluded_date DESC NULLS LAST" in normalized
    assert "c.first_contract_date IS NULL" in normalized



def test_procurement_profile_awards_use_opening_date_cohort() -> None:
    normalized = " ".join(_PROCUREMENT_PROFILE_ACTIVITIES_QUERY.split())

    award_date = "COALESCE((a.opening_at AT TIME ZONE 'Asia/Seoul')::date,a.final_award_date)"
    assert f"{award_date} AS activity_date" in normalized
    assert "'opening_at_or_final_award_date'::text AS attribution_date_basis" in normalized
    assert f"{award_date} >= %(period_from)s" in normalized
    assert f"{award_date} < %(period_to)s" in normalized

