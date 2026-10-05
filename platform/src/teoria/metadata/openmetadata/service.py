from __future__ import annotations

from typing import Any

from teoria.metadata.models import MetadataPage, MetadataStatus, TableDetail
from teoria.metadata.openmetadata.client import OpenMetadataClient
from teoria.metadata.openmetadata.mapper import page, table_detail


class OpenMetadataService:
    def __init__(self, client: OpenMetadataClient, *, base_url: str, database_service: str) -> None:
        self.client = client
        self.base_url = base_url
        self.database_service = database_service

    async def status(self) -> MetadataStatus:
        # Probe an endpoint that needs the same catalog permission as the UI.
        # The public version endpoint alone can look healthy while the configured
        # token is missing or cannot read metadata.
        await self.client.get("v1/tables", params={"limit": 1})
        return MetadataStatus(enabled=True, available=True, base_url=self.base_url, database_service=self.database_service)

    async def list_services(self, *, limit: int = 50, after: str | None = None) -> MetadataPage:
        return page(await self._list("v1/services/databaseServices", limit, after), "databaseService")

    async def list_databases(self, *, service: str | None, limit: int = 50, after: str | None = None) -> MetadataPage:
        return page(await self._list("v1/databases", limit, after, service=service), "database")

    async def list_schemas(self, *, database: str | None, limit: int = 50, after: str | None = None) -> MetadataPage:
        return page(await self._list("v1/databaseSchemas", limit, after, database=database), "databaseSchema")

    async def list_tables(self, *, database_schema: str | None, limit: int = 50, after: str | None = None) -> MetadataPage:
        return page(await self._list("v1/tables", limit, after, databaseSchema=database_schema), "table")

    async def get_table(self, fully_qualified_name: str) -> TableDetail:
        return table_detail(await self.client.get_table_by_name(fully_qualified_name))

    async def get_table_lineage(self, table_id: str, *, upstream_depth: int = 1, downstream_depth: int = 1) -> dict[str, Any]:
        return await self.client.get(
            f"v1/tables/{table_id}/lineage",
            params={"upstreamDepth": upstream_depth, "downstreamDepth": downstream_depth},
        )

    async def _list(self, path: str, limit: int, after: str | None, **filters: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(max(limit, 1), 100), "fields": "owners,tags,domains"}
        if after:
            params["after"] = after
        params.update({key: value for key, value in filters.items() if value})
        return await self.client.get(path, params=params)
