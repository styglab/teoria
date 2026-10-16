from unittest.mock import AsyncMock, Mock

from teoria.domains.public_procurement.market_analysis.classification import (
    _enrich_procurement_classification,
)


async def test_missing_hierarchy_is_loaded_before_inheriting_notice_classification():
    cursor = Mock(
        fetchall=AsyncMock(
            return_value=[
                {
                    "procurement_classification_number": "81111599",
                    "procurement_large_classification_name": "ICT",
                    "procurement_middle_classification_name": "Software",
                    "purchase_items": ["development"],
                }
            ]
        )
    )
    connection = Mock(execute=AsyncMock(return_value=cursor))
    rows = [
        {"bid_notice_id": "synthetic", "procurement_classification_number": "81111599"},
        {"bid_notice_id": "synthetic"},
    ]
    await _enrich_procurement_classification(connection, rows)
    assert rows[0]["procurement_large_classification_name"] == "ICT"
    assert rows[1]["procurement_middle_classification_name"] == "Software"
    assert rows[1]["procurement_classification_number"] == "81111599"
    connection.execute.assert_awaited_once()
    assert connection.execute.call_args.args[1] == {
        "classification_numbers": ["81111599"]
    }
    cursor.fetchall.assert_awaited_once()


async def test_complete_hierarchy_needs_no_database_query():
    connection = Mock(execute=AsyncMock())
    rows = [
        {
            "bid_notice_id": "synthetic",
            "procurement_classification_number": "81111599",
            "procurement_large_classification_name": "ICT",
        }
    ]
    await _enrich_procurement_classification(connection, rows)
    connection.execute.assert_not_awaited()
