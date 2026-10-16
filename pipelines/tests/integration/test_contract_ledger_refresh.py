"""A refresh must preserve requests enqueued while its SQL is running."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.domains.public_procurement.contracts.models import NormalizedBatch
from teoria_pipelines.domains.public_procurement.contracts.repository import (
    ContractRepository,
)
from teoria_pipelines.persistence import PostgresStore

DATABASE_URL = os.environ.get("TEORIA_TEST_DATA_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="TEORIA_TEST_DATA_DATABASE_URL is not set"
)


@pytest.fixture(scope="module", autouse=True)
async def migrated_database():
    await PostgresStore(DATABASE_URL).apply_migrations(
        Path(__file__).parents[2] / "database/migrations"
    )


def test_notice_view_no_longer_reads_archived_extractions():
    with psycopg.connect(DATABASE_URL) as connection:
        definition = connection.execute(
            "SELECT pg_get_viewdef('public_procurement.runtime_bid_notices_base'::regclass,true)"
        ).fetchone()[0]
    assert "bid_eligibility" not in definition
    assert "bid_notice_documents" not in definition
    assert "lineage_summaries" in definition


@pytest.mark.parametrize("fail_refresh", [False, True])
async def test_enqueue_during_refresh_survives_completion_or_failure(
    monkeypatch, fail_refresh
):
    connect = psycopg.connect
    async_connect = psycopg.AsyncConnection.connect
    repository = ContractRepository(DATABASE_URL)
    code = "test_" + uuid4().hex
    batch = NormalizedBatch(contracts=[{"procurement_classification_number": code}])
    await repository.enqueue_contract_event_ledger_refresh(batch)
    competing_refreshes = []

    class DuringRefreshConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        async def __aenter__(self):
            await self.connection.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.connection.__aexit__(*args)

        async def execute(self, sql, parameters=None):
            if (
                "SELECT field_code FROM ingestion.contract_event_ledger_refresh_queue"
                in sql
            ):
                # Isolate this worker to the synthetic field in the shared test DB.
                return await self.connection.execute(
                    "SELECT field_code FROM ingestion.contract_event_ledger_refresh_queue "
                    "WHERE field_code=%s",
                    (code,),
                )
            if "SELECT public_procurement.refresh_contract_event_company_ledger" in sql:
                # A second connection runs while the first worker holds its lock.
                competing_refreshes.append(
                    (await repository.refresh_contract_event_ledger())
                )
                await repository.enqueue_contract_event_ledger_refresh(batch)
                if fail_refresh:
                    raise psycopg.OperationalError("synthetic refresh failure")
            return await self.connection.execute(sql, parameters)

    async def intercepted_connect(*args, **kwargs):
        return DuringRefreshConnection(await async_connect(*args, **kwargs))

    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                psycopg.AsyncConnection,
                "connect",
                intercepted_connect,
            )
            assert (await repository.refresh_contract_event_ledger()) == (
                0 if fail_refresh else 1
            )
        assert competing_refreshes == [0]
        with connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT request_version,attempts,last_error FROM "
                "ingestion.contract_event_ledger_refresh_queue WHERE field_code=%s",
                (code,),
            ).fetchone()
        assert row == (2, 0, None)
        await repository.refresh_contract_event_ledger(batch_size=10000)
        with connect(DATABASE_URL) as connection:
            assert (
                connection.execute(
                    "SELECT 1 FROM ingestion.contract_event_ledger_refresh_queue WHERE field_code=%s",
                    (code,),
                ).fetchone()
                is None
            )
    finally:
        with connect(DATABASE_URL) as connection:
            connection.execute(
                "DELETE FROM ingestion.contract_event_ledger_refresh_queue WHERE field_code=%s",
                (code,),
            )
