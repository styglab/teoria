import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.model_operations.admin_router import create_model_operations_router
from teoria.settings import Settings


def test_authentication_and_explicit_pipeline_parameters():
    calls = []

    async def transport(request):
        calls.append(request)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    app = FastAPI()
    app.include_router(
        create_model_operations_router(
            authorizer=AdminAuthorizer(
                Settings(admin_auth_mode="bearer", admin_api_token="test-token")
            ),
            client=client,
            enabled=True,
            prefect_url="http://prefect/api",
            prefect_auth="user:password",
            mlflow_url="http://mlflow",
            inference_url="http://inference",
            inference_token="secret",
        )
    )
    with TestClient(app) as api:
        assert api.get("/v1/admin/model-operations/pipelines").status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        body = {"idempotency_key": "12345678-1234-1234-1234-123456789012"}
        assert (
            api.post(
                "/v1/admin/model-operations/pipelines/arbitrary/runs",
                json=body,
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            api.post(
                "/v1/admin/model-operations/pipelines/demo-deploy-customer-churn/runs",
                json=body,
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            api.post(
                "/v1/admin/model-operations/pipelines/demo-seed-customers/runs",
                json={**body, "requested_by": "forged"},
                headers=headers,
            ).status_code
            == 422
        )
        assert not calls


def make_api(handler):
    app = FastAPI()
    app.include_router(
        create_model_operations_router(
            authorizer=AdminAuthorizer(
                Settings(admin_auth_mode="bearer", admin_api_token="test-token")
            ),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            enabled=True,
            prefect_url="http://prefect/api",
            prefect_auth="user:password",
            mlflow_url="http://mlflow",
            inference_url="http://inference",
            inference_token="inference-secret",
        )
    )
    return TestClient(app)


def test_run_detail_does_not_expose_unrelated_flow_logs():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if "/flow_runs/" in request.url.path:
            return httpx.Response(200, json={"id": "run", "deployment_id": "foreign"})
        return httpx.Response(
            200, json=[{"id": "allowed", "name": "demo-seed-customers"}]
        )

    with make_api(handler) as api:
        response = api.get(
            "/v1/admin/model-operations/runs/12345678-1234-1234-1234-123456789012",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 404
    assert not any("/logs/" in path or "/task_runs/" in path for path in calls)


def test_run_detail_redacts_secrets_and_allowlists_parameters():
    def handler(request):
        path = request.url.path
        if path.endswith("/deployments/filter"):
            return httpx.Response(
                200, json=[{"id": "allowed", "name": "demo-seed-customers"}]
            )
        if path.endswith("/flow_runs/filter"):
            return httpx.Response(200, json=[])
        if "/flow_runs/" in path:
            return httpx.Response(
                200,
                json={
                    "id": "run",
                    "deployment_id": "allowed",
                    "name": "demo",
                    "parameters": {"requested_by": "admin", "db_url": "private"},
                    "state": {"message": "test-token"},
                },
            )
        if "/task_runs/" in path:
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "id": "log",
                    "timestamp": "2026-10-27T00:00:00Z",
                    "level": 40,
                    "message": "postgresql://user:dbpass@db/demo Bearer bearer-secret inference-secret user:password test-token",
                }
            ],
        )

    with make_api(handler) as api:
        response = api.get(
            "/v1/admin/model-operations/runs/12345678-1234-1234-1234-123456789012",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["parameters"] == {"requested_by": "admin"}
    for secret in [
        "dbpass",
        "bearer-secret",
        "inference-secret",
        "user:password",
        "test-token",
    ]:
        assert secret not in response.text


def test_history_pagination_and_state_are_applied_at_prefect():
    import json

    requests = []

    def handler(request):
        body = json.loads(request.content or "{}")
        requests.append((request.url.path, body))
        if "/deployments/" in request.url.path:
            return httpx.Response(
                200, json=[{"id": "allowed", "name": "demo-seed-customers"}]
            )
        return httpx.Response(
            200, json=61 if request.url.path.endswith("/count") else []
        )

    with make_api(handler) as api:
        response = api.get(
            "/v1/admin/model-operations/pipelines?pipeline_id=demo-seed-customers&state=FAILED&offset=25&limit=25",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200 and response.json()["total"] == 61
    body = next(body for path, body in requests if body.get("offset") == 25)
    assert body["flow_runs"]["state"]["type"]["any_"] == ["FAILED"]
    assert body["deployments"]["id"]["any_"] == ["allowed"]
    assert "expected_start_time" not in body["flow_runs"]


def test_registry_reads_multiple_models_and_selected_model_versions():
    calls = []

    def handler(request):
        calls.append(request)
        if "registered-models/search" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "registered_models": [
                        {"name": "churn", "description": "Customer churn"},
                        {"name": "forecast", "description": "Revenue forecast"},
                    ],
                    "next_page_token": "next-models",
                },
            )
        if "model-versions/search" in request.url.path:
            assert request.url.params["filter"] == "name = 'forecast'"
            return httpx.Response(
                200,
                json={
                    "model_versions": [
                        {"name": "forecast", "version": "3", "run_id": "run"}
                    ]
                },
            )
        if "/runs/get" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "run": {
                        "data": {
                            "metrics": [{"key": "rmse", "value": 1.2}],
                            "params": [],
                        }
                    }
                },
            )
        return httpx.Response(200, json={"status": "ok", "model_version": 1})

    with make_api(handler) as api:
        response = api.get(
            "/v1/admin/model-operations/models?model_name=forecast",
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data["registered_models"]) == 2
    assert data["model_name"] == "forecast"
    assert data["items"][0]["metrics"] == {"rmse": 1.2}
    assert data["serving"]["model_name"] != "forecast"
    assert data["next_page_token"] == "next-models"


def test_auto_deployment_is_only_applicable_to_parent_pipeline():
    with make_api(lambda request: httpx.Response(200, json=[])) as api:
        response = api.post(
            "/v1/admin/model-operations/pipelines/demo-seed-customers/runs",
            headers={"Authorization": "Bearer test-token"},
            json={
                "idempotency_key": "12345678-1234-1234-1234-123456789012",
                "deploy": True,
            },
        )
    assert response.status_code == 422
