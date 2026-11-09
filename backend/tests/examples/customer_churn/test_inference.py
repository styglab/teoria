import pytest
from pydantic import ValidationError
from teoria.examples.customer_churn.inference import PredictionInput


def test_inference_contract_rejects_identity_fields_and_out_of_range_values():
    values = dict(
        tenure_months=12, monthly_spend=50, login_days_30d=8, support_tickets_30d=3
    )
    assert PredictionInput(**values).tenure_months == 12
    for changes in (
        {"email": "customer@example.invalid"},
        {"login_days_30d": 31},
        {"tenure_months": True},
        {"monthly_spend": float("nan")},
    ):
        with pytest.raises(ValidationError):
            PredictionInput(**{**values, **changes})


def test_example_router_preserves_authentication_service_schema_and_prediction_proxy():
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.examples.customer_churn.admin_router import create_customer_churn_router
    from teoria.platform.access_control.auth import AdminAuthorizer
    from teoria.settings import Settings

    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "model_version": 2})
        assert request.headers["Authorization"] == "Bearer inference-secret"
        return httpx.Response(
            200,
            json={
                "model_version": 2,
                "churn_probability": 0.4,
                "synthetic_demo_only": True,
            },
        )

    app = FastAPI()
    app.include_router(
        create_customer_churn_router(
            authorizer=AdminAuthorizer(
                Settings(admin_auth_mode="bearer", admin_api_token="admin-secret")
            ),
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            enabled=True,
            inference_url="http://inference",
            inference_token="inference-secret",
        )
    )
    with TestClient(app) as api:
        assert api.get("/v1/admin/model-operations/services").status_code == 401
        assert not requests
        headers = {"Authorization": "Bearer admin-secret"}
        service = api.get(
            "/v1/admin/model-operations/services", headers=headers
        ).json()["items"][0]
        assert service["id"] == "customer-churn" and service["model_version"] == 2
        assert "tenure_months" in service["request_schema"]["properties"]
        response = api.post(
            "/v1/admin/model-operations/predict",
            headers=headers,
            json={
                "tenure_months": 12,
                "monthly_spend": 50,
                "login_days_30d": 8,
                "support_tickets_30d": 3,
            },
        )
        assert (
            response.status_code == 200 and response.json()["churn_probability"] == 0.4
        )
        before = len(requests)
        assert (
            api.post(
                "/v1/admin/model-operations/predict",
                headers=headers,
                json={"email": "invalid"},
            ).status_code
            == 422
        )
        assert len(requests) == before
