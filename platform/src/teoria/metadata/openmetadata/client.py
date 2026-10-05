from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class OpenMetadataError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class OpenMetadataClient:
    def __init__(self, base_url: str, token: str | None, *, timeout_seconds: float, verify_ssl: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def patch(self, path: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request(
            "PATCH", path, json=operations,
            headers={"Content-Type": "application/json-patch+json"},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, verify=self.verify_ssl) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers={**self.headers, **(headers or {})},
                    params=params,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise OpenMetadataError("openmetadata_timeout", "OpenMetadata request timed out") from exc
        except httpx.HTTPError as exc:
            raise OpenMetadataError("openmetadata_unreachable", "OpenMetadata is unreachable") from exc
        if not response.is_success:
            raise OpenMetadataError(
                "openmetadata_api_error",
                f"OpenMetadata returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise OpenMetadataError("openmetadata_invalid_response", "OpenMetadata returned invalid JSON") from exc

    async def get_table_by_name(self, fully_qualified_name: str) -> dict[str, Any]:
        return await self.get(
            f"v1/tables/name/{quote(fully_qualified_name, safe='')}",
            params={"fields": "owners,tags,domains,columns,database,databaseSchema"},
        )

    async def update_table_description(self, table_id: str, description: str, *, has_description: bool) -> dict[str, Any]:
        return await self.patch(
            f"v1/tables/{quote(table_id, safe='')}",
            [{"op": "replace" if has_description else "add", "path": "/description", "value": description}],
        )
