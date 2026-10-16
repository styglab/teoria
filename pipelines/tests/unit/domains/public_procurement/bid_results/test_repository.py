from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from teoria_pipelines.domains.public_procurement.bid_results.repository import (
    BidResultRepository,
)
from teoria_pipelines.models import CollectionWindow, RawProviderRecord


async def test_bid_opening_retry_claim_excludes_terminal_partial_results() -> None:
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    result = MagicMock()
    result.fetchall.return_value = []
    result.description = []
    connection.execute.return_value = result
    result.fetchall = AsyncMock(return_value=[])

    with patch(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        records = await BidResultRepository(
            "postgresql://unused"
        ).claim_bid_opening_enrichment(
            uuid4(),
            "retry",
            60,
            15,
        )

    assert records == []
    sql = connection.execute.call_args_list[0].args[0]
    assert "q.status='retry_wait'" in sql
    assert "partial_completed" not in sql


async def test_bid_opening_failures_have_distinct_terminal_retry_limits() -> None:
    connection = MagicMock()
    connection.__aenter__.return_value = connection
    connection.execute = AsyncMock(return_value=AsyncMock())
    cursor = MagicMock()
    cursor.__aenter__.return_value = cursor
    cursor.executemany = AsyncMock()
    connection.cursor.return_value = cursor
    record = RawProviderRecord(
        raw_record_id=uuid4(),
        execution_id=uuid4(),
        connector_id="pps_bid_result_api",
        operation_id="list_service_bid_awards",
        window=CollectionWindow(date(2026, 1, 1), date(2026, 1, 1)),
        fetched_at=datetime.now(timezone.utc),
        source_record_hash="award-hash",
        payload={
            "bidNtceNo": "N1",
            "bidNtceOrd": "000",
            "bidClsfcNo": "0",
            "rbidNo": "000",
        },
    )

    with patch(
        "teoria_pipelines.persistence.connection.psycopg.AsyncConnection.connect",
        return_value=connection,
    ):
        await BidResultRepository("postgresql://unused").finish_bid_opening_enrichment(
            [record],
            [record],
        )

    incomplete_sql = cursor.executemany.call_args_list[0].args[0]
    lookup_sql = cursor.executemany.call_args_list[1].args[0]
    assert "q.attempts+1>=3 THEN 'partial_completed'" in incomplete_sql
    assert "q.attempts+1>=3 THEN 'infinity'::timestamptz" in incomplete_sql
    assert "attempts+1>=5 THEN 'permanent_failure'" in lookup_sql
    assert "attempts+1>=5 THEN 'infinity'::timestamptz" in lookup_sql


def test_bid_opening_retry_migration_requeues_unverified_legacy_completion() -> None:
    migration = (
        Path(__file__).parents[5]
        / "database"
        / "migrations"
        / "087_bound_bid_opening_retries.sql"
    ).read_text()

    assert "queue.status = 'completed'" in migration
    assert "checked.selected_business_numbers IS NULL" in migration
    assert "last_error_code = 'legacy_selection_unverified'" in migration
    assert "WHERE status = 'retry_wait'" in migration
    assert (
        "q.status IN ('partial_completed','permanent_failure') THEN 'failed'"
        in migration
    )
