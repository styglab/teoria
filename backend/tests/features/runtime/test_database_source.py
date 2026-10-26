from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.runtime.capability.binder import CapabilityBinder
from teoria.features.runtime.source.database import DatabaseSourceExecutor


REGISTRIES = Path("backend/tests/fixtures/registry")


async def test_database_search_counts_roots_and_pages_with_stable_sort() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    count_result = AsyncMock()
    count_result.fetchone.return_value = {"count": 21}
    rows_result = AsyncMock()
    rows_result.fetchall.return_value = []
    connection.execute.side_effect = [count_result, rows_result]

    query = {
        "filters": [],
        "search": {"fields": ["name"], "value": "100%_test"},
        "order_by": [
            {"field": "created_date", "direction": "desc", "nulls": "last"},
            {"field": "record_id", "direction": "desc", "nulls": None},
        ],
        "pagination": {"page": 2, "page_size": 20, "root_field": "record_id"},
    }

    with patch(
        "teoria.integrations.application_database.postgres.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        result = await DatabaseSourceExecutor(
            {
                "TEORIA_RUNTIME_DATA_DATABASE_URL": "postgresql://unused",
            }
        ).execute(catalog, "example_data", "records", query)

    count_call, rows_call = connection.execute.call_args_list
    assert 'COUNT(DISTINCT "record_id")' in count_call.args[0].as_string()
    assert count_call.args[1] == [r"%100\%\_test%", "\\"]
    assert "ILIKE %s ESCAPE %s" in count_call.args[0].as_string()
    rows_sql = rows_call.args[0].as_string()
    assert '"created_date" DESC NULLS LAST, "record_id" DESC' in rows_sql
    assert rows_sql.endswith("LIMIT %s OFFSET %s")
    assert rows_call.args[1] == [r"%100\%\_test%", "\\", 20, 20]
    assert result.pagination == {
        "page": 2,
        "page_size": 20,
        "total_items": 21,
        "total_pages": 2,
    }


async def test_database_search_filters_scalar_in_array_field() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    rows_result = AsyncMock()
    rows_result.fetchall.return_value = []
    connection.execute.return_value = rows_result

    with patch(
        "teoria.integrations.application_database.postgres.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        await DatabaseSourceExecutor(
            {
                "TEORIA_RUNTIME_DATA_DATABASE_URL": "postgresql://unused",
            }
        ).execute(
            catalog,
            "example_data",
            "records",
            {
                "filters": [
                    {
                        "field": "categories",
                        "operator": "contains",
                        "value": "81111599",
                    }
                ],
            },
        )

    statement, parameters = connection.execute.call_args.args
    assert '%s = ANY("categories")' in statement.as_string()
    assert parameters == ["81111599", 1000]
