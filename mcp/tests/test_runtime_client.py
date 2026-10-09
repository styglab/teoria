import httpx
import pytest

from teoria_mcp.runtime_client import RuntimeAPIClient, RuntimeAPIError


def _client(handler, *, max_attempts=3, delays=None):
    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    async def sleep(delay):
        if delays is not None:
            delays.append(delay)

    return RuntimeAPIClient(
        "http://runtime.test",
        "secret",
        max_attempts=max_attempts,
        retry_backoff_seconds=0.5,
        client_factory=client_factory,
        sleep=sleep,
    )


@pytest.mark.asyncio
async def test_discovery_retries_transient_status_and_honors_retry_after() -> None:
    attempts = 0
    delays = []

    def handler(request):
        nonlocal attempts
        attempts += 1
        assert request.headers["authorization"] == "Bearer secret"
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"capabilities": [{"id": "find_contracts"}]})

    capabilities = await _client(handler, delays=delays).list_capabilities()

    assert capabilities == [{"id": "find_contracts"}]
    assert attempts == 2
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_execution_is_not_automatically_retried() -> None:
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            json={"detail": {"code": "policy_unavailable", "message": "OPA unavailable"}},
        )

    with pytest.raises(RuntimeAPIError) as raised:
        await _client(handler).execute("find_contracts", {}, {})

    assert attempts == 1
    assert raised.value.to_dict() == {
        "code": "policy_unavailable",
        "message": "OPA unavailable",
        "attempts": 1,
        "retryable": True,
        "http_status": 503,
    }


@pytest.mark.asyncio
async def test_discovery_reports_exhausted_network_retries() -> None:
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(RuntimeAPIError) as raised:
        await _client(handler, max_attempts=2).list_capabilities()

    assert attempts == 2
    assert raised.value.code == "runtime_network_error"
    assert raised.value.attempts == 2
    assert raised.value.retryable is True


@pytest.mark.asyncio
async def test_rejects_invalid_discovery_shape() -> None:
    def handler(request):
        return httpx.Response(200, json={"capabilities": {}})

    with pytest.raises(RuntimeAPIError) as raised:
        await _client(handler).list_capabilities()

    assert raised.value.code == "invalid_runtime_response"
    assert raised.value.retryable is False


def test_rejects_invalid_retry_configuration() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RuntimeAPIClient("http://runtime.test", "secret", max_attempts=0)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        RuntimeAPIClient(
            "http://runtime.test", "secret", retry_backoff_seconds=-0.1
        )
