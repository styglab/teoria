from unittest.mock import AsyncMock

import pytest

from teoria.integrations.prefect import maintenance


def state():
    return {
        "pools": [
            {"name": "models", "is_paused": True},
            {"name": "documents", "is_paused": False},
        ],
        "schedules": [
            {
                "deployment_id": "model",
                "id": "old-model",
                "active": False,
                "schedule": {"cron": "0 0 * * *"},
            },
            {
                "deployment_id": "doc",
                "id": "old-doc",
                "active": True,
                "schedule": {"cron": "0 1 * * *"},
            },
        ],
        "deployment_ids": ["model", "doc"],
        "deployment_pools": {"model": "models", "doc": "documents"},
    }


@pytest.mark.asyncio
async def test_resume_preserves_operator_pause_and_leaves_disabled_features_paused(
    monkeypatch,
):
    monkeypatch.setattr(maintenance, "selected_pools", lambda: {"models"})
    client = AsyncMock()
    client.request.return_value = {
        "schedules": [{"id": "new-model", "schedule": {"cron": "0 0 * * *"}}]
    }
    remaining = await maintenance.set_paused(client, state(), restore=True)
    client.request.assert_any_await("PATCH", "/work_pools/models", {"is_paused": True})
    client.update_schedule.assert_awaited_once_with(
        "model", "new-model", {"active": False}
    )
    assert remaining["pools"] == [{"name": "documents", "is_paused": False}]
    assert remaining["deployment_ids"] == ["doc"]
    assert not any(
        call.args[1] == "/work_pools/documents"
        for call in client.request.await_args_list
    )


@pytest.mark.asyncio
async def test_pause_stops_all_owned_dispatch_and_schedules():
    client = AsyncMock()
    await maintenance.set_paused(client, state(), restore=False)
    client.request.assert_any_await("PATCH", "/work_pools/models", {"is_paused": True})
    client.request.assert_any_await(
        "PATCH", "/work_pools/documents", {"is_paused": True}
    )
    client.update_schedule.assert_any_await("doc", "old-doc", {"active": False})


@pytest.mark.asyncio
async def test_snapshot_excludes_other_projects_and_kubernetes_pools(monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "pool_policies",
        lambda: {"specification_processing": {"documents"}},
    )
    client = AsyncMock()
    client.request.side_effect = [
        [
            {"name": "documents", "is_paused": False},
            {"name": "other", "is_paused": False},
            {"name": "documents-k3s", "is_paused": False},
        ],
        [
            {"id": "doc", "work_pool_name": "documents", "schedules": []},
            {"id": "other", "work_pool_name": "other", "schedules": []},
        ],
    ]
    value = await maintenance.snapshot(client)
    assert value["pools"] == [{"name": "documents", "is_paused": False}]
    assert value["deployment_ids"] == ["doc"]
