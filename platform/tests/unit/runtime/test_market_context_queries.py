from teoria.runtime.market_context.queries.outcomes import (
    _PROCUREMENT_OUTCOME_AWARDS_QUERY,
)


def test_procurement_outcome_awards_scopes_before_lineage_lookup() -> None:
    normalized = " ".join(_PROCUREMENT_OUTCOME_AWARDS_QUERY.split())

    assert "WITH scoped_awards AS MATERIALIZED" in normalized
    assert "FROM scoped_awards a LEFT JOIN LATERAL" in normalized
    assert (
        "WHERE n.notice_number=a.notice_number "
        "AND n.notice_order=a.notice_order LIMIT 1"
    ) in normalized
