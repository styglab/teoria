from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, uuid4

from teoria_provider.executor import ProviderExecutor
from teoria_provider.errors import ProviderExecutionError
from teoria_provider.request_builder import ProviderRequestBuilder
from teoria_provider.response_validator import ProviderResponseValidator
from teoria_provider.schema import ProviderDefinition

from teoria_pipelines.connectors.pps_contracts import ConnectorResponseError, _resolve
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord


AWARD_OPERATIONS = [
    "list_goods_bid_awards",
    "list_construction_bid_awards",
    "list_service_bid_awards",
    "list_foreign_bid_awards",
]


class PPSBidResultClient:
    def __init__(self, definition: ProviderDefinition, *, path: Path,
                 executor: ProviderExecutor | None = None, page_size: int = 100,
                 max_pages: int = 1000, opening_concurrency: int = 8,
                 opening_requests_per_second: float = 4.0) -> None:
        self.definition = definition
        self.path = path
        self.executor = executor or ProviderExecutor()
        self.page_size = page_size
        self.max_pages = max_pages
        if opening_concurrency < 1:
            raise ValueError("opening_concurrency must be positive")
        if opening_requests_per_second <= 0:
            raise ValueError("opening_requests_per_second must be positive")
        self.opening_concurrency = opening_concurrency
        self.opening_requests_per_second = opening_requests_per_second
        self._opening_rate_lock = asyncio.Lock()
        self._next_opening_request_at = 0.0
        self._opening_rate_limiter_active = False

    @classmethod
    def from_pipeline_root(cls, root: Path | str, **values: Any) -> "PPSBidResultClient":
        catalog = PipelineLoader(root).load()
        registry = catalog.connectors["pps_bid_result_api"]
        return cls(registry.connector, path=catalog.connector_paths["pps_bid_result_api"], **values)

    async def fetch_award_operation(self, execution_id: UUID, window: CollectionWindow,
                                    operation_id: str) -> ExtractedBatch:
        if operation_id not in AWARD_OPERATIONS:
            raise ValueError(f"unsupported award operation '{operation_id}'")
        return await self._fetch_pages(execution_id, window, operation_id, {
            "inqryDiv": "2",
            "inqryBgnDt": window.start.strftime("%Y%m%d0000"),
            "inqryEndDt": window.end.strftime("%Y%m%d2359"),
        })

    async def fetch_opening_results(self, execution_id: UUID, window: CollectionWindow,
                                    award_records: Iterable[RawProviderRecord]) -> ExtractedBatch:
        keys = sorted({
            (
                str(record.payload.get("bidNtceNo") or "").strip(),
                str(record.payload.get("bidNtceOrd") or "").strip(),
                str(record.payload.get("bidClsfcNo") or "").strip(),
                str(record.payload.get("rbidNo") or "").strip(),
            )
            for record in award_records if record.operation_id in AWARD_OPERATIONS
        })
        semaphore = asyncio.Semaphore(self.opening_concurrency)

        async def fetch_one(key: tuple[str, str, str, str]) -> ExtractedBatch:
            notice_number, notice_order, classification_number, rebid_number = key
            if not notice_number:
                return ExtractedBatch(execution_id=execution_id, window=window)
            query = {"bidNtceNo": notice_number}
            if notice_order:
                query["bidNtceOrd"] = notice_order
            if classification_number:
                query["bidClsfcNo"] = classification_number
            if rebid_number:
                query["rbidNo"] = rebid_number
            async with semaphore:
                for attempt in range(5):
                    try:
                        return await self._fetch_pages(
                            execution_id, window, "list_completed_opening_results", query
                        )
                    except ProviderExecutionError as exc:
                        if exc.http_status != 429 or attempt == 4:
                            raise
                        delay = 2 ** (attempt + 1)
                        await self._penalize_opening_rate(delay)
                        await asyncio.sleep(delay)
            raise RuntimeError("opening result retry loop exhausted")

        self._opening_rate_limiter_active = True
        try:
            async with self.executor:
                batches = await asyncio.gather(*(fetch_one(key) for key in keys))
        finally:
            self._opening_rate_limiter_active = False
        result = ExtractedBatch(execution_id=execution_id, window=window)
        for batch in batches:
            result.records.extend(batch.records)
            result.pages += batch.pages
        return result

    async def _fetch_pages(self, execution_id: UUID, window: CollectionWindow,
                           operation_id: str, query: dict[str, Any]) -> ExtractedBatch:
        operation = next(item for item in self.definition.operations if item.id == operation_id)
        records: list[RawProviderRecord] = []
        for page_number in range(1, self.max_pages + 1):
            request = ProviderRequestBuilder().build(
                self.definition,
                operation_id,
                {"query": {"numOfRows": self.page_size, "pageNo": page_number, **query}},
                path=self.path,
            )
            if self._opening_rate_limiter_active:
                await self._wait_for_opening_rate_slot()
            response = await self.executor.execute(request)
            diagnostics = ProviderResponseValidator().validate(
                self.definition, operation_id, response, path=self.path
            )
            if diagnostics:
                raise ConnectorResponseError("; ".join(str(item) for item in diagnostics))
            total_count = int(_resolve(response.body, operation.pagination.total_count))
            if total_count == 0:
                return ExtractedBatch(execution_id=execution_id, window=window, pages=page_number)
            payloads = _resolve(response.body, operation.response.data.record_path)
            fetched_at = datetime.now(timezone.utc)
            for payload in payloads:
                canonical = json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                records.append(RawProviderRecord(
                    raw_record_id=uuid4(), execution_id=execution_id,
                    connector_id=self.definition.id, operation_id=operation_id,
                    window=window, fetched_at=fetched_at,
                    source_record_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    payload=payload,
                ))
            if page_number * self.page_size >= total_count:
                return ExtractedBatch(
                    execution_id=execution_id, window=window,
                    records=records, pages=page_number,
                )
        raise ConnectorResponseError(
            f"operation '{operation_id}' exceeded max_pages={self.max_pages}"
        )

    async def _wait_for_opening_rate_slot(self) -> None:
        async with self._opening_rate_lock:
            now = time.monotonic()
            delay = max(0.0, self._next_opening_request_at - now)
            if delay:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next_opening_request_at = max(now, self._next_opening_request_at) + (
                1.0 / self.opening_requests_per_second
            )

    async def _penalize_opening_rate(self, delay: float) -> None:
        async with self._opening_rate_lock:
            self._next_opening_request_at = max(
                self._next_opening_request_at, time.monotonic() + delay
            )
