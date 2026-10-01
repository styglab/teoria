from pathlib import Path
from unittest.mock import MagicMock, patch

from teoria.registry.loader import RegistryLoader
from teoria.runtime.capability.binder import CapabilityBinder
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


def test_database_search_filters_scalar_in_array_field() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    connection.execute.return_value = rows_result

    with patch("teoria.runtime.source.database.psycopg.connect", return_value=connection):
        DatabaseSourceExecutor({
            "TEORIA_RUNTIME_DATA_DATABASE_URL": "postgresql://unused",
        }).execute(catalog, "teoria_public_procurement", "bid_notices", {
            "filters": [{
                "field": "field_codes", "operator": "contains", "value": "81111599",
            }],
        })

    statement, parameters = connection.execute.call_args.args
    assert '%s = ANY("field_codes")' in statement.as_string()
    assert parameters == ["81111599", 1000]


def test_procurement_searches_bind_hierarchy_filters_before_pagination() -> None:
    catalog = RegistryLoader(REGISTRIES).load()
    binder = CapabilityBinder()
    cases = (
        ("search_bid_awards", "bid_awards", {
            "opening_at_from": "2026-01-01T00:00:00+00:00",
            "opening_at_to": "2026-10-01T23:59:59+00:00",
            "demand_organization_code": "Z004905",
            "work_type": "service",
        }),
        ("search_public_procurement_contracts", "contracts", {
            "concluded_date_from": "2026-01-01",
            "concluded_date_to": "2026-10-01",
            "contracting_organization_code": "Z004905",
            "work_type": "service",
        }),
    )
    for capability_id, relation_id, base_inputs in cases:
        capability = catalog.capabilities[capability_id]
        inputs = {
            **base_inputs,
            "large_category": "ICT 서비스",
            "middle_category": "SW 및 시스템 개발",
            "field_code": "81111599",
            "page": 2,
            "page_size": 5,
        }
        query = binder.bind(catalog, capability, capability.steps[0], inputs)
        filters = {
            (item["field"], item["value"]) for item in query["filters"]
        }
        assert ("large_category", "ICT 서비스") in filters
        assert ("middle_category", "SW 및 시스템 개발") in filters
        assert ("field_code", "81111599") in filters
        assert ("work_type", "service") in filters
        assert query["pagination"]["page"] == 2
        assert query["pagination"]["page_size"] == 5
        assert capability.steps[0].call.endswith(relation_id)
