"""App-owned pools live across requests and close at shutdown; injected clients stay borrowed."""

import httpx
import pytest
from fastapi.testclient import TestClient

from teoria.entrypoints.admin_api import create_admin_app
from teoria.entrypoints.runtime_api import create_runtime_app
from teoria.integrations.openmetadata.client import OpenMetadataClient
from teoria.features.runtime.context.runtime_client import ContextRuntimeClient
from teoria.features.access_control.policy import OpaPolicyEvaluator, PolicyPrincipal
from teoria.settings import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["metadata", "context", "policy"])
async def test_borrowed_http_clients_are_reused_and_not_closed(adapter):
    calls = []

    async def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"result": {"allow": True, "reason": "test"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        if adapter == "metadata":
            resource = OpenMetadataClient(
                "http://metadata",
                None,
                timeout_seconds=1,
                verify_ssl=True,
                client=client,
            )

            async def call():
                return await resource.get("v1/tables")
        elif adapter == "context":
            resource = ContextRuntimeClient("http://runtime", "test", client=client)

            async def call():
                return await resource.execute("test_capability", {})
        else:
            resource = OpaPolicyEvaluator("http://policy", client=client)

            async def call():
                return await resource.decide(
                    principal=PolicyPrincipal("test"), action="read", resource={}
                )

        async with resource:
            await call()
            await call()
        assert len(calls) == 2
        assert not client.is_closed
    finally:
        await client.aclose()


def test_admin_lifespan_opens_and_closes_only_owned_metadata_pool():
    app = create_admin_app(settings=Settings(openmetadata_enabled=True))
    adapter = app.state.admin_services.metadata_service.client
    assert adapter._http_client is None
    with TestClient(app) as client:
        pool = adapter._http_client
        assert pool is not None and not pool.is_closed
        assert client.get("/health").status_code == 200
    assert pool.is_closed and adapter._http_client is None


def test_runtime_lifespan_closes_provider_and_policy_pools():
    app = create_runtime_app(
        settings=Settings(runtime_api_token="test", policy_mode="opa")
    )
    services = app.state.runtime_services
    with TestClient(app) as client:
        provider = services.runner.executor._client
        policy = services.policy_evaluator._http_client
        assert provider is not None and not provider.is_closed
        assert policy is not None and not policy.is_closed
        assert client.get("/health").status_code == 200
    assert provider.is_closed and policy.is_closed


def test_development_preflight_accepts_profile_update_method():
    with TestClient(create_admin_app()) as client:
        response = client.options(
            "/v1/admin/goods/normalization-profiles/test",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
            },
        )
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]
