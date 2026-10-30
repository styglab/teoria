import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from teoria.entrypoints import asset_assessment_worker as worker
from teoria.settings import Settings


@pytest.mark.asyncio
async def test_shutdown_finishes_current_diagnosis_without_claiming_another(
    monkeypatch,
):
    stop = asyncio.Event()
    repository = MagicMock()
    repository.claim = AsyncMock(return_value={"assessment_id": "test"})
    service = MagicMock()

    async def process(job):
        stop.set()

    service.process = AsyncMock(side_effect=process)
    settings = Settings(
        assessment_enabled=True,
        app_database_url="postgresql://synthetic",
        openmetadata_enabled=True,
    )
    monkeypatch.setattr(worker, "bootstrap_settings", lambda: settings)
    monkeypatch.setattr(worker, "AssessmentRepository", lambda _: repository)
    monkeypatch.setattr(worker, "OpenMetadataClient", lambda *a, **kw: AsyncMock())
    monkeypatch.setattr(worker, "AssessmentModelClient", MagicMock())
    monkeypatch.setattr(worker, "AssetAssessmentService", lambda *a, **kw: service)
    await worker.run(stop_event=stop)
    repository.claim.assert_awaited_once()
    service.process.assert_awaited_once()
