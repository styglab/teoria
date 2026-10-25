from teoria.integrations.data_operations.persistence.postgres import _sanitize_postgres_value


def test_postgres_boundary_recursively_removes_nul_characters() -> None:
    value = {"original_text": "입찰\x00자격", "evidence": [{"excerpt": "공동\x00수급"}]}

    assert _sanitize_postgres_value(value) == {
        "original_text": "입찰 자격",
        "evidence": [{"excerpt": "공동 수급"}],
    }
