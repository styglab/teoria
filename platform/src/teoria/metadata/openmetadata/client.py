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

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=payload)

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
            params={"fields": "owners,tags,domains,columns,database,databaseSchema,testSuite"},
        )

    async def update_table_description(self, table_id: str, description: str, *, has_description: bool) -> dict[str, Any]:
        return await self.patch(
            f"v1/tables/{quote(table_id, safe='')}",
            [{"op": "replace" if has_description else "add", "path": "/description", "value": description}],
        )

    async def update_column_description(
        self, table_id: str, *, column_index: int, description: str,
        has_description: bool,
    ) -> dict[str, Any]:
        return await self.patch(
            f"v1/tables/{quote(table_id, safe='')}",
            [{
                "op": "replace" if has_description else "add",
                "path": f"/columns/{column_index}/description",
                "value": description,
            }],
        )

    async def create_glossary_term(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "glossary", "parent", "name", "displayName", "description",
            "synonyms", "relatedTerms", "references", "reviewers", "owners",
            "tags", "domains",
        }
        return await self.post(
            "v1/glossaryTerms", {key: value for key, value in payload.items() if key in allowed},
        )

    async def create_test_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name", "displayName", "description", "testDefinition", "entityLink",
            "parameterValues", "owners", "reviewers", "computePassedFailedRowCount",
            "useDynamicAssertion", "tags", "dimensionColumns", "domains",
        }
        return await self.post(
            "v1/dataQuality/testCases",
            {key: value for key, value in payload.items() if key in allowed},
        )

    async def get_test_case(self, test_case_id: str) -> dict[str, Any]:
        return await self.get(f"v1/dataQuality/testCases/{quote(test_case_id, safe='')}")

    async def create_test_suite(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name", "displayName", "description", "owners",
            "basicEntityReference", "domains", "tags", "reviewers",
        }
        return await self.post(
            "v1/dataQuality/testSuites/basic",
            {key: value for key, value in payload.items() if key in allowed},
        )

    async def get_test_suite(self, test_suite_id: str) -> dict[str, Any]:
        return await self.get(f"v1/dataQuality/testSuites/{quote(test_suite_id, safe='')}")

    async def assign_column_glossary_term(
        self, table_id: str, *, column_index: int, term_fqn: str, already_assigned: bool
    ) -> dict[str, Any]:
        if already_assigned:
            return await self.get(f"v1/tables/{quote(table_id, safe='')}", params={"fields": "columns"})
        return await self.patch(
            f"v1/tables/{quote(table_id, safe='')}",
            [{
                "op": "add",
                "path": f"/columns/{column_index}/tags/-",
                "value": {
                    "tagFQN": term_fqn,
                    "source": "Glossary",
                    "labelType": "Manual",
                    "state": "Confirmed",
                },
            }],
        )
