from __future__ import annotations

from typing import Any

import httpx


class ContextRuntimeError(RuntimeError):
    pass


class ContextRuntimeClient:
    """HTTP boundary from semantic context composition to Capability Runtime."""

    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 150.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout_seconds = timeout_seconds

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
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v1/capabilities/{capability_id}:execute",
                headers=headers,
                json={"inputs": inputs, "options": {"max_objects": max_objects}},
            )
        if not response.is_success:
            raise ContextRuntimeError(f"Runtime API returned HTTP {response.status_code}")
        return response.json()
