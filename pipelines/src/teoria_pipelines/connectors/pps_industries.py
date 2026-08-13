from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from teoria_provider.executor import ProviderExecutor
from teoria_provider.request_builder import ProviderRequestBuilder
from teoria_provider.response_validator import ProviderResponseValidator

from teoria_pipelines.connectors.pps_contracts import ConnectorResponseError, _resolve
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord


class PPSIndustryClient:
    def __init__(self, definition, *, path: Path, executor: ProviderExecutor, page_size: int = 100):
        self.definition, self.path, self.executor, self.page_size = definition, path, executor, page_size

    @classmethod
    def from_pipeline_root(cls, root, **values):
        catalog = PipelineLoader(root).load()
        registry = catalog.connectors["pps_industry_api"]
        return cls(registry.connector, path=catalog.connector_paths["pps_industry_api"], **values)

    async def fetch_all(self, execution_id: UUID) -> ExtractedBatch:
        window = CollectionWindow(date.today(), date.today())
        operation_id, page, records = "list_industry_base_laws", 1, []
        operation = self.definition.operations[0]
        while True:
            request = ProviderRequestBuilder().build(self.definition, operation_id, {
                "query": {"numOfRows": self.page_size, "pageNo": page}
            }, path=self.path)
            response = await self.executor.execute(request)
            diagnostics = ProviderResponseValidator().validate(
                self.definition, operation_id, response, path=self.path
            )
            if diagnostics:
                raise ConnectorResponseError("; ".join(map(str, diagnostics)))
            total = int(_resolve(response.body, operation.pagination.total_count))
            payloads = _resolve(response.body, operation.response.data.record_path) if total else []
            fetched_at = datetime.now(timezone.utc)
            for payload in payloads:
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                records.append(RawProviderRecord(
                    uuid4(), execution_id, self.definition.id, operation_id, window, fetched_at,
                    hashlib.sha256(canonical.encode()).hexdigest(), payload,
                ))
            if page * self.page_size >= total:
                return ExtractedBatch(execution_id, window, records, page)
            page += 1
