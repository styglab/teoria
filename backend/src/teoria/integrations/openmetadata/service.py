from __future__ import annotations

from typing import Any
import math
import asyncio

from teoria.features.metadata_management.catalog.models import MetadataPage, MetadataStatus, TableDetail, TableSampleData, TableProfileData
from teoria.integrations.openmetadata.client import OpenMetadataClient, OpenMetadataError
from teoria.integrations.openmetadata.mapper import entity_reference, page, table_detail


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

    async def search_tables(self, **options) -> MetadataPage:
        from teoria.integrations.openmetadata.catalog_search import search_tables

        return await search_tables(self.client, **options)

    async def table_counts(self, *, database_schema: str | None, query: str = "") -> dict[str, int]:
        # Four fixed count-only requests; no entity bodies are collected or persisted.
        kinds = ("all", "description", "owner", "tags")
        pages = await asyncio.gather(*(
            self.search_tables(database_schema=database_schema, query=query, missing=kind, limit=0)
            for kind in kinds
        ))
        return dict(zip(kinds, (result.total for result in pages)))

    async def get_table(self, fully_qualified_name: str) -> TableDetail:
        return table_detail(await self.client.get_table_by_name(fully_qualified_name))

    async def get_table_samples(self, table_id: str, *, limit: int = 10,
                                include_values: bool = False) -> TableSampleData:
        if not 1 <= limit <= 50:
            raise ValueError("sample limit must be between 1 and 50")
        document = await self.client.get_table_sample_data(table_id)
        reference = self._table_reference(document, table_id)
        sample = document.get("sampleData")
        if sample is None:
            return TableSampleData(reference=reference, available=False, reason="not_collected")
        if not isinstance(sample, dict):
            raise OpenMetadataError("openmetadata_invalid_response", "Invalid sample data envelope")
        columns, rows = sample.get("columns", []), sample.get("rows", [])
        if (not isinstance(columns, list) or any(not isinstance(c, str) for c in columns)
                or not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != len(columns) for r in rows)):
            raise OpenMetadataError("openmetadata_invalid_response", "Invalid sample data shape")
        # Bounds apply to this transient response, not to source data completeness.
        displayed_columns = columns[:100]
        output = []
        truncated = len(rows) > limit or len(columns) > 100
        for row in rows[:limit]:
            values = []
            for value in row[:100]:
                if value is None:
                    values.append(None)
                elif not include_values:
                    values.append("[REDACTED]")
                elif isinstance(value, (dict, list)):
                    # Nested structures can contain unrelated personal fields.
                    values.append("[STRUCTURED VALUE]")
                elif isinstance(value, str) and len(value) > 500:
                    values.append(value[:500])
                    truncated = True
                else:
                    values.append(value)
            output.append(values)
        return TableSampleData(reference=reference, available=True, columns=displayed_columns,
            rows=output, stored_row_count=len(rows), truncated=truncated, values_included=include_values)

    async def get_table_profile(self, table_id: str) -> TableProfileData:
        table = await self.client.get_table_by_id(table_id)
        fqn = table.get("fullyQualifiedName")
        if not isinstance(fqn, str) or not fqn:
            raise OpenMetadataError("openmetadata_invalid_response", "Table FQN is missing")
        document = await self.client.get_latest_table_profile(fqn)
        reference = self._table_reference(document, table_id)
        # Keep counts, proportions and lengths only. min/max, distinctValues,
        # topValues and custom SQL metrics can expose source values.
        allowed_table = {"timestamp", "rowCount", "columnCount", "profileSample"}
        allowed_column = {"timestamp", "valuesCount", "nullCount", "nullProportion", "distinctCount",
                          "distinctProportion", "uniqueCount", "uniqueProportion", "minLength", "maxLength", "avgLength"}

        def metrics(profile, allowed):
            if profile is None:
                return {}
            if not isinstance(profile, dict):
                raise OpenMetadataError("openmetadata_invalid_response", "Invalid profile envelope")
            return {key: value for key, value in profile.items() if key in allowed
                    and (value is None or isinstance(value, (int, float)) and not isinstance(value, bool)
                         and math.isfinite(value))}

        table_metrics = metrics(document.get("profile"), allowed_table)
        column_metrics = []

        def collect(columns, parent=""):
            if not isinstance(columns, list) or any(not isinstance(c, dict) for c in columns):
                raise OpenMetadataError("openmetadata_invalid_response", "Invalid profile columns")
            for column in columns:
                name = column.get("fullyQualifiedName") or parent + column.get("name", "")
                profile = metrics(column.get("profile"), allowed_column)
                if profile:
                    column_metrics.append({"name": name, "metrics": profile})
                collect(column.get("children") or [], name + ".")

        collect(document.get("columns") or [])
        available = bool(table_metrics or column_metrics)
        return TableProfileData(reference=reference, available=available, table_metrics=table_metrics,
            column_metrics=column_metrics, reason=None if available else "not_collected")

    @staticmethod
    def _table_reference(document, expected_id):
        if not isinstance(document, dict) or str(document.get("id", "")).lower() != expected_id.lower():
            raise OpenMetadataError("openmetadata_invalid_response", "Table identity does not match")
        return entity_reference(document, "table")

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
