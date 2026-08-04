from __future__ import annotations

from typing import Any

import httpx


class RuntimeAPIError(RuntimeError):
    pass


class RuntimeAPIClient:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 150.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout_seconds = timeout_seconds

    async def list_capabilities(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.base_url}/v1/capabilities", headers=self.headers)
        self._raise_for_status(response)
        return response.json()["capabilities"]

    async def execute(
        self,
        capability_id: str,
        inputs: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v1/capabilities/{capability_id}:execute",
                headers=self.headers,
                json={"inputs": inputs, "options": options},
            )
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeAPIError(f"Runtime API returned HTTP {response.status_code}: {detail}")
