from pathlib import Path
from unittest.mock import MagicMock, patch

from teoria.registry.loader import RegistryLoader
from teoria.runtime.source.database import DatabaseSourceExecutor


REGISTRIES = Path(__file__).parents[3] / "registries"


def test_database_search_counts_roots_and_pages_with_stable_sort() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    count_result = MagicMock()
    count_result.fetchone.return_value = {"count": 21}
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    connection.execute.side_effect = [count_result, rows_result]

    query = {
        "filters": [],
        "search": {"fields": ["notice_name"], "value": "100%_test"},
        "order_by": [
            {"field": "notice_published_at", "direction": "desc", "nulls": "last"},
            {"field": "bid_notice_id", "direction": "desc", "nulls": None},
        ],
        "pagination": {"page": 2, "page_size": 20, "root_field": "bid_notice_id"},
    }

    with patch("teoria.runtime.source.database.psycopg.connect", return_value=connection):
        result = DatabaseSourceExecutor({
            "TEORIA_RUNTIME_DATA_DATABASE_URL": "postgresql://unused",
        }).execute(catalog, "teoria_public_procurement", "bid_notices", query)

    count_call, rows_call = connection.execute.call_args_list
    assert 'COUNT(DISTINCT "bid_notice_id")' in count_call.args[0].as_string()
    assert count_call.args[1] == [r"%100\%\_test%", "\\"]
    assert 'ILIKE %s ESCAPE %s' in count_call.args[0].as_string()
    rows_sql = rows_call.args[0].as_string()
    assert '"notice_published_at" DESC NULLS LAST, "bid_notice_id" DESC' in rows_sql
    assert rows_sql.endswith("LIMIT %s OFFSET %s")
    assert rows_call.args[1] == [r"%100\%\_test%", "\\", 20, 20]
    assert result.pagination == {
        "page": 2, "page_size": 20, "total_items": 21, "total_pages": 2,
    }
