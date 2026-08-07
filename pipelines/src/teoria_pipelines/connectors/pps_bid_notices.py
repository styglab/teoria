from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from teoria_provider.executor import ProviderExecutor
from teoria_provider.request_builder import ProviderRequestBuilder
from teoria_provider.response_validator import ProviderResponseValidator
from teoria_provider.schema import ProviderDefinition

from teoria_pipelines.connectors.pps_contracts import ConnectorResponseError, _resolve
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import BidNoticeKey, CollectionWindow, ExtractedBatch, RawProviderRecord


NOTICE_OPERATIONS = [
    "list_construction_bid_notices", "list_service_bid_notices",
    "list_foreign_bid_notices", "list_goods_bid_notices", "list_other_bid_notices",
]
ENRICHMENT_OPERATIONS = ["list_license_restrictions", "list_participation_regions"]


class PPSBidNoticeClient:
    def __init__(self, definition: ProviderDefinition, *, path: Path,
                 executor: ProviderExecutor | None = None, page_size: int = 100,
                 max_pages: int = 1000,
                 enrichment_requests_per_second: float = 5.0) -> None:
        self.definition = definition
        self.path = path
        self.executor = executor or ProviderExecutor()
        self.page_size = page_size
        self.max_pages = max_pages
        if enrichment_requests_per_second <= 0:
            raise ValueError("enrichment_requests_per_second must be positive")
        self.enrichment_request_interval = 1 / enrichment_requests_per_second
        self._enrichment_rate_lock = asyncio.Lock()
        self._next_enrichment_request_at = 0.0

    @classmethod
    def from_pipeline_root(cls, root: Path | str, **values: Any) -> "PPSBidNoticeClient":
        catalog = PipelineLoader(root).load()
        registry = catalog.connectors["pps_bid_notice_api"]
        return cls(registry.connector, path=catalog.connector_paths["pps_bid_notice_api"], **values)

    async def fetch_notice_operation(self, execution_id: UUID, window: CollectionWindow,
                                     operation_id: str) -> ExtractedBatch:
        return await self._fetch_pages(execution_id, window, operation_id, {
            "inqryDiv": "1",
            "inqryBgnDt": window.start.strftime("%Y%m%d0000"),
            "inqryEndDt": window.end.strftime("%Y%m%d2359"),
            "bidClseExcpYn": "N",
        })

    async def fetch_enrichment(self, execution_id: UUID, window: CollectionWindow,
                               notices: list[BidNoticeKey]) -> ExtractedBatch:
        async def fetch(key: BidNoticeKey, operation_id: str) -> ExtractedBatch:
            await self._wait_for_enrichment_slot()
            return await self._fetch_pages(execution_id, window, operation_id, {
                "inqryDiv": "2", "bidNtceNo": key.notice_number,
                "bidNtceOrd": key.notice_order,
            })

        batches = await asyncio.gather(*(
            fetch(key, operation_id)
            for key in notices
            for operation_id in ENRICHMENT_OPERATIONS
        ))
        return ExtractedBatch(
            execution_id=execution_id, window=window,
            records=[record for batch in batches for record in batch.records],
            pages=sum(batch.pages for batch in batches),
        )

    async def _wait_for_enrichment_slot(self) -> None:
        async with self._enrichment_rate_lock:
            now = time.monotonic()
            delay = max(0.0, self._next_enrichment_request_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_enrichment_request_at = (
                max(now, self._next_enrichment_request_at)
                + self.enrichment_request_interval
            )

    async def _fetch_pages(self, execution_id: UUID, window: CollectionWindow,
                           operation_id: str, query: dict[str, Any]) -> ExtractedBatch:
        operation = next(item for item in self.definition.operations if item.id == operation_id)
        records: list[RawProviderRecord] = []
        for page_number in range(1, self.max_pages + 1):
            request = ProviderRequestBuilder().build(
                self.definition, operation_id,
                {"query": {"numOfRows": self.page_size, "pageNo": page_number, **query}},
                path=self.path,
            )
            response = await self.executor.execute(request)
            diagnostics = ProviderResponseValidator().validate(
                self.definition, operation_id, response, path=self.path
            )
            if diagnostics:
                raise ConnectorResponseError("; ".join(str(item) for item in diagnostics))
            total_count = int(_resolve(response.body, operation.pagination.total_count))
            payloads = [] if total_count == 0 else _resolve(
                response.body, operation.response.data.record_path
            )
            fetched_at = datetime.now(timezone.utc)
            for payload in payloads:
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                records.append(RawProviderRecord(
                    raw_record_id=uuid4(), execution_id=execution_id,
                    connector_id=self.definition.id, operation_id=operation_id,
                    window=window, fetched_at=fetched_at,
                    source_record_hash=hashlib.sha256(canonical.encode()).hexdigest(),
                    payload=payload,
                ))
            if total_count == 0 or page_number * self.page_size >= total_count:
                return ExtractedBatch(
                    execution_id=execution_id, window=window, records=records, pages=page_number
                )
        raise ConnectorResponseError(f"operation '{operation_id}' exceeded max_pages={self.max_pages}")
