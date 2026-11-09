from __future__ import annotations

from typing import Any

import httpx


class ContextRuntimeError(RuntimeError):
    pass


class ContextRuntimeClient:
    """HTTP boundary from semantic context composition to Capability Runtime."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 150.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout_seconds = timeout_seconds
        self._http_client = client
        self._owns_http_client = False

    async def __aenter__(self):
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_http_client = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self._owns_http_client:
            client, self._http_client = self._http_client, None
            self._owns_http_client = False
            await client.aclose()

    async def _post(self, url, **kwargs):
        if self._http_client is not None:
            return await self._http_client.post(url, **kwargs)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.post(url, **kwargs)

    async def execute(
        self,
        capability_id: str,
        inputs: dict[str, Any],
        *,
        max_objects: int = 1000,
        actor: str | None = None,
        roles: frozenset[str] = frozenset(),
        service: str | None = None,
    ) -> dict[str, Any]:
        headers = dict(self.headers)
        if actor:
            headers["X-Teoria-Actor"] = actor
        if roles:
            headers["X-Teoria-Roles"] = ",".join(sorted(roles))
        if service:
            headers["X-Teoria-Service"] = service
        response = await self._post(
            f"{self.base_url}/v1/capabilities/{capability_id}:execute",
            headers=headers,
            json={"inputs": inputs, "options": {"max_objects": max_objects}},
        )
        if not response.is_success:
            raise ContextRuntimeError(
                f"Runtime API returned HTTP {response.status_code}"
            )
        return response.json()
