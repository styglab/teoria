import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.workflow_management.admin_router import create_workflow_router
from teoria.settings import Settings

HEADERS = {"Authorization": "Bearer test-token"}
SCHEDULE = "12345678-1234-1234-1234-123456789012"
RUN = "22345678-1234-1234-1234-123456789012"


def make_api(handler, *, mlops=False, roles="metadata_admin"):
    app = FastAPI()
    app.include_router(
        create_workflow_router(
            authorizer=AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer",
                    admin_api_token="test-token",
                    admin_api_actor="authenticated:operator",
                    admin_api_roles=roles,
                )
            ),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            prefect_url="http://prefect/api",
            prefect_auth="user:password",
            mlops_enabled=mlops,
        )
    )
    return TestClient(app)


def fixture_handler(calls, *, foreign=False, state="RUNNING", invalid_cron=False):
    def handler(request):
        body = json.loads(request.content or "{}")
        calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/deployments/filter"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "metadata",
                        "name": "openmetadata-postgres-metadata-sync",
                        "schedules": [
                            {
                                "id": SCHEDULE,
                                "active": True,
                                "schedule": {
                                    "cron": "0 5 * * *",
                                    "timezone": "Asia/Seoul",
                                    "day_or": True,
                                },
                            }
                        ],
                    }
                ],
            )
        if "/schedules/" in request.url.path:
            return httpx.Response(422, json={}) if invalid_cron else httpx.Response(204)
        if "/create_flow_run" in request.url.path:
            return httpx.Response(201, json={"id": RUN, "name": "manual-run"})
        if "/set_state" in request.url.path:
            return httpx.Response(200, json={"status": "ACCEPT"})
        if request.method == "GET" and "/flow_runs/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": RUN,
                    "deployment_id": "archived" if foreign else "metadata",
                    "state_type": state,
                },
            )
        return httpx.Response(
            200, json=0 if request.url.path.endswith("/count") else []
        )

    return handler


def test_catalog_is_available_without_mlops_and_excludes_demo_helpers():
    calls = []
    with make_api(fixture_handler(calls)) as api:
        r = api.get("/v1/admin/workflows/pipelines", headers=HEADERS)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 6
    assert not any(x["id"].startswith("demo-") for x in items)
    sync = next(x for x in items if x["id"] == "openmetadata-postgres-metadata-sync")
    assert sync["schedules"][0]["schedule"]["timezone"] == "Asia/Seoul"
    assert any(
        "after_" in body.get("flow_runs", {}).get("expected_start_time", {})
        for _, _, body in calls
    )


def test_schedule_update_is_scoped_and_preserves_existing_cron_options():
    calls = []
    with make_api(fixture_handler(calls)) as api:
        r = api.patch(
            f"/v1/admin/workflows/pipelines/openmetadata-postgres-metadata-sync/schedules/{SCHEDULE}",
            headers=HEADERS,
            json={"cron": "0 6 * * *", "timezone": "UTC"},
        )
    assert r.status_code == 200
    patch = next(body for method, _, body in calls if method == "PATCH")
    assert patch == {
        "schedule": {"cron": "0 6 * * *", "timezone": "UTC", "day_or": True}
    }


def test_schedule_update_rejects_wrong_owner_bad_timezone_and_provider_validation():
    for schedule, payload, invalid_cron, expected in [
        (RUN, {"active": False}, False, 404),
        (SCHEDULE, {"cron": "0 6 * * *", "timezone": "Not/AZone"}, False, 422),
        (SCHEDULE, {"cron": "invalid cron", "timezone": "UTC"}, True, 422),
    ]:
        calls = []
        with make_api(fixture_handler(calls, invalid_cron=invalid_cron)) as api:
            r = api.patch(
                f"/v1/admin/workflows/pipelines/openmetadata-postgres-metadata-sync/schedules/{schedule}",
                headers=HEADERS,
                json=payload,
            )
        assert r.status_code == expected


def test_readers_cannot_change_schedule_or_cancel_or_run():
    calls = []
    with make_api(fixture_handler(calls), roles="metadata_reviewer") as api:
        assert (
            api.patch(
                f"/v1/admin/workflows/pipelines/openmetadata-postgres-metadata-sync/schedules/{SCHEDULE}",
                headers=HEADERS,
                json={"active": False},
            ).status_code
            == 403
        )
        assert (
            api.post(
                f"/v1/admin/workflows/runs/{RUN}/cancel", headers=HEADERS, json={}
            ).status_code
            == 403
        )
        assert (
            api.post(
                "/v1/admin/workflows/pipelines/openmetadata-postgres-metadata-sync/runs",
                headers=HEADERS,
                json={"idempotency_key": RUN},
            ).status_code
            == 403
        )
    assert not calls


def test_cancellation_checks_run_ownership_and_finished_state():
    for foreign, state, expected in [
        (True, "RUNNING", 404),
        (False, "COMPLETED", 409),
        (False, "RUNNING", 202),
    ]:
        calls = []
        with make_api(fixture_handler(calls, foreign=foreign, state=state)) as api:
            r = api.post(
                f"/v1/admin/workflows/runs/{RUN}/cancel", headers=HEADERS, json={}
            )
        assert r.status_code == expected
        writes = [b for m, p, b in calls if p.endswith("/set_state")]
        if expected == 202:
            assert writes[0]["state"]["type"] == "CANCELLING"
            assert "authenticated:operator" in writes[0]["state"]["message"]
        else:
            assert not writes


def test_manual_run_uses_deployment_defaults_and_authenticated_actor():
    calls = []
    with make_api(fixture_handler(calls)) as api:
        r = api.post(
            "/v1/admin/workflows/pipelines/openmetadata-postgres-metadata-sync/runs",
            headers=HEADERS,
            json={"idempotency_key": RUN},
        )
    assert r.status_code == 202
    body = next(b for _, p, b in calls if p.endswith("/create_flow_run"))
    assert body["parameters"] == {}
    assert "teoria:actor:authenticated:operator" in body["tags"]


def test_specification_inputs_are_validated_before_creating_a_run():
    calls = []
    with make_api(fixture_handler(calls)) as api:
        r = api.post(
            "/v1/admin/workflows/pipelines/specification-document-processing/runs",
            headers=HEADERS,
            json={"idempotency_key": RUN, "manifest": {"mode": "standard_management"}},
        )
    assert r.status_code == 422
    assert not any(p.endswith("/create_flow_run") for _, p, _ in calls)


def test_prefect_immediate_cancelled_state_is_a_successful_stop_request():
    calls = []
    original = fixture_handler(calls, state="SCHEDULED")

    def handler(request):
        if request.url.path.endswith("/set_state"):
            return httpx.Response(
                200, json={"status": "REJECT", "state": {"type": "CANCELLED"}}
            )
        return original(request)

    with make_api(handler) as api:
        result = api.post(
            f"/v1/admin/workflows/runs/{RUN}/cancel", headers=HEADERS, json={}
        )
    assert result.status_code == 202
