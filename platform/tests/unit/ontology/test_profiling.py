from teoria.ontology.profiling import PROFILE_QUERIES, _json_values


def test_profile_queries_are_unique_and_read_only() -> None:
    keys = [query.key for query in PROFILE_QUERIES]
    assert len(keys) == len(set(keys))
    for query in PROFILE_QUERIES:
        normalized = query.sql.upper()
        assert "SELECT" in normalized
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP "):
            assert forbidden not in normalized


def test_deep_queries_are_explicit() -> None:
    deep = {query.key for query in PROFILE_QUERIES if query.deep}
    assert deep == {"contract_notice_linkage", "business_name_collisions"}


def test_json_values_preserves_integer_counts() -> None:
    assert _json_values({"total": 3}) == {"total": 3}
