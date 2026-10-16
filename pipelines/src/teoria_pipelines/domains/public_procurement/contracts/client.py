from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from uuid import UUID, uuid4

from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.request_builder import ProviderRequestBuilder
from teoria_provider_api.response_validator import ProviderResponseValidator
from teoria_provider_api.schema import ProviderDefinition

from teoria_pipelines.domains.public_procurement.provider_response import (
    ConnectorResponseError,
    _provider_error,
    _resolve,
)
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord


class PPSContractClient:
    def __init__(
        self,
        definition: ProviderDefinition,
        *,
        path: Path,
        executor: ProviderExecutor | None = None,
        page_size: int = 100,
        max_pages: int = 1000,
        requests_per_second: float = 1000.0,
        provider_error_max_attempts: int = 1,
        provider_error_backoff_seconds: float = 60.0,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if provider_error_max_attempts < 1:
            raise ValueError("provider_error_max_attempts must be at least one")
        self.definition = definition
        self.path = path
        self.executor = executor or ProviderExecutor()
        self.page_size = page_size
        self.max_pages = max_pages
        self.request_interval = 1 / requests_per_second
        self.provider_error_max_attempts = provider_error_max_attempts
        self.provider_error_backoff_seconds = provider_error_backoff_seconds
        self._next_request_at = 0.0

    @classmethod
    def from_pipeline_root(cls, root: Path | str, **values: Any) -> "PPSContractClient":
        catalog = PipelineLoader(root).load()
        registry = catalog.connectors["pps_contract_api"]
        return cls(
            registry.connector,
            path=catalog.connector_paths["pps_contract_api"],
            **values,
        )

    async def fetch_window(
        self, execution_id: UUID, window: CollectionWindow, operation_ids: list[str]
    ) -> ExtractedBatch:
        batch = ExtractedBatch(execution_id=execution_id, window=window)
        for operation_id in operation_ids:
            operation_batch = await self.fetch_operation(
                execution_id, window, operation_id
            )
            batch.records.extend(operation_batch.records)
            batch.pages += operation_batch.pages
        return batch

    async def fetch_operation(
        self, execution_id: UUID, window: CollectionWindow, operation_id: str
    ) -> ExtractedBatch:
        operation = next(
            item for item in self.definition.operations if item.id == operation_id
        )
        page_number = 1
        records: list[RawProviderRecord] = []
        while page_number <= self.max_pages:
            request = ProviderRequestBuilder().build(
                self.definition,
                operation_id,
                {
                    "query": {
                        "numOfRows": self.page_size,
                        "pageNo": page_number,
                        "inqryDiv": "1",
                        "inqryBgnDate": window.start.strftime("%Y%m%d"),
                        "inqryEndDate": window.end.strftime("%Y%m%d"),
                    }
                },
                path=self.path,
            )
            response = await self._execute_with_provider_retry(request)
            diagnostics = ProviderResponseValidator().validate(
                self.definition, operation_id, response, path=self.path
            )
            if diagnostics:
                raise ConnectorResponseError(
                    "; ".join(str(item) for item in diagnostics)
                )
            total_count = int(_resolve(response.body, operation.pagination.total_count))
            if total_count == 0:
                return ExtractedBatch(
                    execution_id=execution_id,
                    window=window,
                    pages=page_number,
                )
            payloads = _resolve(response.body, operation.response.data.record_path)
            fetched_at = datetime.now(timezone.utc)
            for payload in payloads:
                canonical = json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                records.append(
                    RawProviderRecord(
                        raw_record_id=uuid4(),
                        execution_id=execution_id,
                        connector_id=self.definition.id,
                        operation_id=operation_id,
                        window=window,
                        fetched_at=fetched_at,
                        source_record_hash=hashlib.sha256(
                            canonical.encode("utf-8")
                        ).hexdigest(),
                        payload=payload,
                    )
                )
            if page_number * self.page_size >= total_count:
                return ExtractedBatch(
                    execution_id=execution_id,
                    window=window,
                    records=records,
                    pages=page_number,
                )
            page_number += 1
        raise ConnectorResponseError(
            f"operation '{operation_id}' exceeded max_pages={self.max_pages}"
        )

    async def _execute_with_provider_retry(self, request: Any):
        for attempt in range(1, self.provider_error_max_attempts + 1):
            await self._wait_for_request_slot()
            response = await self.executor.execute(request)
            provider_error = _provider_error(response.body)
            if provider_error is None:
                return response
            code, message = provider_error
            retryable = code in {"22", "99"}
            if not retryable or attempt == self.provider_error_max_attempts:
                raise ConnectorResponseError(
                    f"provider_error code={code or 'unknown'} message={message or 'unknown'} "
                    f"attempts={attempt} retryable={str(retryable).lower()}"
                )
            await asyncio.sleep(self.provider_error_backoff_seconds * attempt)
        raise RuntimeError("provider response retry exhausted")

    async def _wait_for_request_slot(self) -> None:
        now = time.monotonic()
        delay = max(0.0, self._next_request_at - now)
        if delay:
            await asyncio.sleep(delay)
        self._next_request_at = time.monotonic() + self.request_interval
