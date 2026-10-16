from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Iterable
from uuid import UUID, uuid4

from teoria_provider_api.errors import ProviderExecutionError
from teoria_provider_api.executor import ProviderExecutor
from teoria_provider_api.request_builder import ProviderRequestBuilder
from teoria_provider_api.response_validator import ProviderResponseValidator
from teoria_provider_api.schema import ProviderDefinition

from teoria_pipelines.domains.public_procurement.provider_response import (
    ConnectorResponseError,
    _resolve,
)
from teoria_pipelines.loader import PipelineLoader
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord
from teoria_pipelines.domains.public_procurement.bid_results.models import (
    NoticeOutcomeResultBatch,
    OpeningResultBatch,
)


AWARD_OPERATIONS = [
    "list_goods_bid_awards",
    "list_construction_bid_awards",
    "list_service_bid_awards",
    "list_foreign_bid_awards",
]
LOGGER = logging.getLogger(__name__)


class PPSBidResultClient:
    def __init__(
        self,
        definition: ProviderDefinition,
        *,
        path: Path,
        executor: ProviderExecutor | None = None,
        page_size: int = 100,
        max_pages: int = 1000,
        opening_concurrency: int = 8,
        opening_requests_per_second: float = 4.0,
        opening_request_timeout_seconds: float = 20.0,
    ) -> None:
        self.definition = definition
        self.path = path
        self.executor = executor or ProviderExecutor()
        self.page_size = page_size
        self.max_pages = max_pages
        if opening_concurrency < 1:
            raise ValueError("opening_concurrency must be positive")
        if opening_requests_per_second <= 0:
            raise ValueError("opening_requests_per_second must be positive")
        if opening_request_timeout_seconds <= 0:
            raise ValueError("opening_request_timeout_seconds must be positive")
        self.opening_concurrency = opening_concurrency
        self.opening_requests_per_second = opening_requests_per_second
        self.opening_request_timeout_seconds = opening_request_timeout_seconds
        self._opening_rate_lock = asyncio.Lock()
        self._next_opening_request_at = 0.0
        self._opening_rate_limiter_active = False

    @classmethod
    def from_pipeline_root(
        cls, root: Path | str, **values: Any
    ) -> "PPSBidResultClient":
        catalog = PipelineLoader(root).load()
        registry = catalog.connectors["pps_bid_result_api"]
        return cls(
            registry.connector,
            path=catalog.connector_paths["pps_bid_result_api"],
            **values,
        )

    async def fetch_award_operation(
        self, execution_id: UUID, window: CollectionWindow, operation_id: str
    ) -> ExtractedBatch:
        if operation_id not in AWARD_OPERATIONS:
            raise ValueError(f"unsupported award operation '{operation_id}'")
        return await self._fetch_pages(
            execution_id,
            window,
            operation_id,
            {
                "inqryDiv": "2",
                "inqryBgnDt": window.start.strftime("%Y%m%d0000"),
                "inqryEndDt": window.end.strftime("%Y%m%d2359"),
            },
        )

    async def fetch_opening_results(
        self,
        execution_id: UUID,
        window: CollectionWindow,
        award_records: Iterable[RawProviderRecord],
    ) -> OpeningResultBatch:
        awards_by_key = {
            (
                str(record.payload.get("bidNtceNo") or "").strip(),
                str(record.payload.get("bidNtceOrd") or "").strip(),
                str(record.payload.get("bidClsfcNo") or "").strip(),
                str(record.payload.get("rbidNo") or "").strip(),
            ): record
            for record in award_records
            if record.operation_id in AWARD_OPERATIONS
        }
        keys = sorted(awards_by_key)
        semaphore = asyncio.Semaphore(self.opening_concurrency)

        async def fetch_one(
            key: tuple[str, str, str, str],
        ) -> tuple[tuple[str, str, str, str], ExtractedBatch | None]:
            notice_number, notice_order, classification_number, rebid_number = key
            if not notice_number:
                return key, None
            query = {"bidNtceNo": notice_number}
            if notice_order:
                query["bidNtceOrd"] = notice_order
            if classification_number:
                query["bidClsfcNo"] = classification_number
            if rebid_number:
                query["rbidNo"] = rebid_number
            winner_business_number = _business_number(
                awards_by_key[key].payload.get("bidwinnrBizno")
            )
            async with semaphore:
                try:
                    async with asyncio.timeout(self.opening_request_timeout_seconds):
                        for attempt in range(5):
                            try:
                                batch = await self._fetch_pages(
                                    execution_id,
                                    window,
                                    "list_completed_opening_results",
                                    query,
                                    opening_winner_business_number=winner_business_number,
                                    opening_maximum_rank=10,
                                )
                                if (
                                    not batch.records
                                    and int(
                                        awards_by_key[key].payload.get("prtcptCnum")
                                        or 0
                                    )
                                    > 0
                                ):
                                    raise ConnectorResponseError(
                                        "opening response empty for populated award"
                                    )
                                return key, batch
                            except ProviderExecutionError as exc:
                                if exc.http_status != 429 or attempt == 4:
                                    raise
                                delay = 2 ** (attempt + 1)
                                await self._penalize_opening_rate(delay)
                                await asyncio.sleep(delay)
                except (
                    ProviderExecutionError,
                    ConnectorResponseError,
                    TimeoutError,
                ) as exc:
                    LOGGER.warning(
                        "opening lookup isolated notice=%s order=%s classification=%s "
                        "rebid=%s error=%s",
                        notice_number,
                        notice_order,
                        classification_number,
                        rebid_number,
                        type(exc).__name__,
                    )
                    return key, None
            return key, None

        self._opening_rate_limiter_active = True
        try:
            async with self.executor:
                results = await asyncio.gather(*(fetch_one(key) for key in keys))
        finally:
            self._opening_rate_limiter_active = False
        openings = ExtractedBatch(execution_id=execution_id, window=window)
        successful_awards = ExtractedBatch(execution_id=execution_id, window=window)
        failed_awards = ExtractedBatch(execution_id=execution_id, window=window)
        for key, batch in results:
            if batch is None:
                failed_awards.records.append(awards_by_key[key])
                continue
            successful_awards.records.append(awards_by_key[key])
            openings.records.extend(batch.records)
            openings.pages += batch.pages
        LOGGER.info(
            "opening lookup batch completed total=%d successful=%d failed=%d",
            len(keys),
            len(successful_awards.records),
            len(failed_awards.records),
        )
        return OpeningResultBatch(openings, successful_awards, failed_awards)

    async def fetch_failing_results(
        self,
        execution_id: UUID,
        window: CollectionWindow,
        notice_records: Iterable[RawProviderRecord],
    ) -> NoticeOutcomeResultBatch:
        notices_by_number = {
            str(record.payload.get("bidNtceNo") or "").strip(): record
            for record in notice_records
            if str(record.payload.get("bidNtceNo") or "").strip()
        }
        semaphore = asyncio.Semaphore(self.opening_concurrency)

        async def fetch_one(
            notice_number: str,
        ) -> tuple[str, ExtractedBatch | None]:
            async with semaphore:
                try:
                    async with asyncio.timeout(self.opening_request_timeout_seconds):
                        batch = await self._fetch_pages(
                            execution_id,
                            window,
                            "list_failing_opening_results",
                            {"bidNtceNo": notice_number},
                        )
                        return notice_number, batch
                except (
                    ProviderExecutionError,
                    ConnectorResponseError,
                    TimeoutError,
                ) as exc:
                    LOGGER.warning(
                        "failing opening lookup isolated notice=%s error=%s",
                        notice_number,
                        type(exc).__name__,
                    )
                    return notice_number, None

        self._opening_rate_limiter_active = True
        try:
            async with self.executor:
                results = await asyncio.gather(
                    *(
                        fetch_one(notice_number)
                        for notice_number in sorted(notices_by_number)
                    )
                )
        finally:
            self._opening_rate_limiter_active = False
        outcomes = ExtractedBatch(execution_id=execution_id, window=window)
        successful = ExtractedBatch(execution_id=execution_id, window=window)
        failed = ExtractedBatch(execution_id=execution_id, window=window)
        for notice_number, batch in results:
            if batch is None:
                failed.records.append(notices_by_number[notice_number])
                continue
            successful.records.append(notices_by_number[notice_number])
            outcomes.records.extend(batch.records)
            outcomes.pages += batch.pages
        return NoticeOutcomeResultBatch(outcomes, successful, failed)

    async def _fetch_pages(
        self,
        execution_id: UUID,
        window: CollectionWindow,
        operation_id: str,
        query: dict[str, Any],
        *,
        opening_winner_business_number: str | None = None,
        opening_maximum_rank: int | None = None,
    ) -> ExtractedBatch:
        operation = next(
            item for item in self.definition.operations if item.id == operation_id
        )
        records: list[RawProviderRecord] = []
        opening_total: int | None = None
        opening_hashes: set[str] = set()
        for page_number in range(1, self.max_pages + 1):
            request = ProviderRequestBuilder().build(
                self.definition,
                operation_id,
                {
                    "query": {
                        "numOfRows": self.page_size,
                        "pageNo": page_number,
                        **query,
                    }
                },
                path=self.path,
            )
            if self._opening_rate_limiter_active:
                await self._wait_for_opening_rate_slot()
            response = await self.executor.execute(request)
            diagnostics = ProviderResponseValidator().validate(
                self.definition, operation_id, response, path=self.path
            )
            if diagnostics:
                raise ConnectorResponseError(
                    "; ".join(str(item) for item in diagnostics)
                )
            total_count = int(_resolve(response.body, operation.pagination.total_count))
            is_opening = operation_id == "list_completed_opening_results"
            if is_opening:
                if opening_total is not None and total_count != opening_total:
                    raise ConnectorResponseError(
                        "opening total changed during pagination"
                    )
                opening_total = total_count
            if total_count == 0:
                if is_opening and opening_winner_business_number:
                    raise ConnectorResponseError(
                        "opening response omitted the known winner"
                    )
                return ExtractedBatch(
                    execution_id=execution_id, window=window, pages=page_number
                )
            payloads = _resolve(response.body, operation.response.data.record_path)
            if is_opening and len(payloads) != min(
                self.page_size, total_count - len(records)
            ):
                raise ConnectorResponseError("opening response page was truncated")
            fetched_at = datetime.now(timezone.utc)
            for payload in payloads:
                if is_opening and any(
                    str(payload.get(name) or "").strip() != str(value).strip()
                    for name, value in query.items()
                ):
                    raise ConnectorResponseError(
                        "opening response returned a different award key"
                    )
                canonical = json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                if is_opening:
                    if payload_hash in opening_hashes:
                        raise ConnectorResponseError(
                            "opening response repeated a record"
                        )
                    opening_hashes.add(payload_hash)
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
                if is_opening:
                    _validate_opening_winner(records, opening_winner_business_number)
                return ExtractedBatch(
                    execution_id=execution_id,
                    window=window,
                    records=records,
                    pages=page_number,
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


def _business_number(value: object) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _validate_opening_winner(
    records: Iterable[RawProviderRecord], winner: str | None
) -> None:
    if winner and not any(
        _business_number(record.payload.get("prcbdrBizno")) == winner
        for record in records
    ):
        raise ConnectorResponseError("opening response omitted the known winner")
