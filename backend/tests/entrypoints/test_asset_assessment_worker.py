"""Worker cancellation closes both long-lived HTTP clients."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from teoria.entrypoints import asset_assessment_worker as worker


async def test_worker_cancellation_closes_metadata_and_model_connections(monkeypatch):
    settings = SimpleNamespace(
        assessment_enabled=True,
        app_database_url="postgresql://synthetic/test",
        openmetadata_enabled=True,
        openmetadata_base_url="http://metadata.invalid",
        openmetadata_auth_token=None,
        openmetadata_timeout_seconds=5,
        openmetadata_verify_ssl=True,
        assessment_model_url="http://model.invalid/chat",
        assessment_model_name="synthetic",
        assessment_model_token=None,
        assessment_model_timeout_seconds=7,
        assessment_model_max_tokens=100,
        admin_data_database_url=None,
    )
    monkeypatch.setattr(worker, "bootstrap_settings", lambda: settings)
    monkeypatch.setattr(
        worker,
        "AssessmentRepository",
        lambda url: SimpleNamespace(
            claim=AsyncMock(side_effect=asyncio.CancelledError)
        ),
    )
    clients = []
    original = httpx.AsyncClient

    def create_client(**kwargs):
        client = original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs
        )
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    with pytest.raises(asyncio.CancelledError):
        await worker.run()
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)
