from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
from prefect import task
from teoria_provider.executor import ProviderExecutor
from teoria_provider.secrets import EnvironmentSecretProvider

from teoria_pipelines.checkpoints import resolve_incremental_window
from teoria_pipelines.connectors import PPSBidNoticeClient
from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    ExtractedBatch,
    LoadSummary,
    NormalizedBidNoticeBatch,
)
from teoria_pipelines.normalization import normalize_bid_notice_batch
from teoria_pipelines.persistence import ObjectStorage, PostgresStore
from teoria_pipelines.settings import bootstrap_pipeline_settings


PIPELINE_ID = "pps_bid_notice_ingestion"
NOTICE_OPERATIONS = [
    "list_construction_bid_notices", "list_service_bid_notices",
    "list_foreign_bid_notices", "list_goods_bid_notices", "list_other_bid_notices",
]
VIZ_WINDOW = CollectionWindow(date(2026, 8, 1), date(2026, 8, 1))
VIZ_EXTRACTED = ExtractedBatch(execution_id=UUID(int=0), window=VIZ_WINDOW)
VIZ_NORMALIZED = NormalizedBidNoticeBatch()
VIZ_SUMMARY = LoadSummary()
VIZ_NOTICE_LOAD = (VIZ_SUMMARY, [])


def safe_object_file_name(file_name: str | None, checksum: str, suffix: str) -> str:
    candidate = unicodedata.normalize("NFC", file_name or "")
    candidate = candidate.replace("/", "_").replace("\\", "_")
    candidate = re.sub(r"[\x00-\x1f\x7f]", "_", candidate).strip(" .")
    if candidate in {"", ".", ".."}:
        return f"{checksum}{suffix}"
    if len(candidate) > 200:
        stem = Path(candidate).stem[:160].rstrip(" .") or checksum
        extension = Path(candidate).suffix[:20]
        candidate = f"{stem}{extension}"
    return candidate


def _store() -> PostgresStore:
    settings = bootstrap_pipeline_settings()
    return PostgresStore(settings.data_database_url or "")


def _client(pipeline_root: str) -> PPSBidNoticeClient:
    settings = bootstrap_pipeline_settings()
    return PPSBidNoticeClient.from_pipeline_root(
        Path(pipeline_root),
        executor=ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            backoff_seconds=settings.source_retry_backoff_seconds,
            secret_provider=EnvironmentSecretProvider(),
        ),
    )


def _object_storage() -> ObjectStorage:
    settings = bootstrap_pipeline_settings()
    if not all((settings.object_storage_endpoint,
                settings.object_storage_access_key,
                settings.object_storage_secret_key)):
        raise ValueError("bid document object storage configuration is required")
    return ObjectStorage(
        settings.object_storage_endpoint or "",
        settings.object_storage_bucket,
        settings.object_storage_access_key or "",
        settings.object_storage_secret_key or "",
    )


@task(name="입찰공고 수집 구간 결정", viz_return_value=VIZ_WINDOW)
def determine_bid_notice_window(lookback_days: int = 1) -> CollectionWindow:
    return resolve_incremental_window(lookback_days=lookback_days)


@task(name="입찰공고 Operation 수집", retries=2, retry_delay_seconds=60,
      viz_return_value=VIZ_EXTRACTED)
async def extract_bid_notice_operation(execution_id: UUID, window: CollectionWindow,
                                       operation_id: str, pipeline_root: str,
                                       previous_operation: ExtractedBatch | None = None) -> ExtractedBatch:
    del previous_operation
    return await _client(pipeline_root).fetch_notice_operation(execution_id, window, operation_id)


@task(name="입찰공고 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_notices(batch: ExtractedBatch, raw_count: int) -> NormalizedBidNoticeBatch:
    del raw_count
    return normalize_bid_notice_batch(batch)


@task(name="입찰공고 Upsert", retries=2, retry_delay_seconds=5,
      viz_return_value=VIZ_NOTICE_LOAD)
def upsert_bid_notices(batch: NormalizedBidNoticeBatch) -> tuple[LoadSummary, list[BidNoticeKey]]:
    return _store().upsert_bid_notices(batch)


@task(name="공고번호별 면허·지역 수집", retries=2, retry_delay_seconds=60,
      viz_return_value=VIZ_EXTRACTED)
async def extract_bid_notice_enrichment(execution_id: UUID, window: CollectionWindow,
                                        notices: list[BidNoticeKey], pipeline_root: str,
                                        notice_load: tuple[LoadSummary, list[BidNoticeKey]]) -> ExtractedBatch:
    del notice_load
    if not notices:
        return ExtractedBatch(execution_id=execution_id, window=window)
    return await _client(pipeline_root).fetch_enrichment(execution_id, window, notices)


@task(name="면허·지역 정규화", viz_return_value=VIZ_NORMALIZED)
def normalize_bid_notice_enrichment(batch: ExtractedBatch, raw_count: int) -> NormalizedBidNoticeBatch:
    del raw_count
    return normalize_bid_notice_batch(batch)


@task(name="면허·지역 Upsert", retries=2, retry_delay_seconds=5, viz_return_value=VIZ_SUMMARY)
def upsert_bid_notice_enrichment(batch: NormalizedBidNoticeBatch,
                                 notices: list[BidNoticeKey]) -> LoadSummary:
    return _store().upsert_bid_notice_enrichment(batch, notices)


@task(name="입찰공고 적재결과 결합", viz_return_value=VIZ_SUMMARY)
def combine_bid_notice_summary(raw_notice_count: int, raw_enrichment_count: int,
                               notice_load: tuple[LoadSummary, list[BidNoticeKey]],
                               enrichment_load: LoadSummary) -> LoadSummary:
    notices, _ = notice_load
    return LoadSummary(
        raw_records=raw_notice_count + raw_enrichment_count,
        notices=notices.notices,
        documents=notices.documents,
        license_restrictions=enrichment_load.license_restrictions,
        participation_regions=enrichment_load.participation_regions,
    )


@task(name="입찰공고 Checkpoint 갱신", viz_return_value=VIZ_SUMMARY)
def update_bid_notice_checkpoint(execution_id: UUID, cursor_date: date,
                                 summary: LoadSummary) -> LoadSummary:
    _store().update_checkpoint(PIPELINE_ID, cursor_date, execution_id)
    return summary


@task(name="처리대상 첨부파일 선택", viz_return_value=[])
def claim_bid_documents(batch_size: int = 500) -> list[dict]:
    settings = bootstrap_pipeline_settings()
    return _store().claim_pending_documents(batch_size, settings.bid_document_max_attempts)


@task(name="첨부파일 Object Storage 저장", retries=1, retry_delay_seconds=60,
      viz_return_value=VIZ_SUMMARY)
async def process_bid_documents(documents: list[dict], concurrency: int = 8) -> LoadSummary:
    settings = bootstrap_pipeline_settings()
    if not documents:
        return LoadSummary()
    storage = _object_storage()
    store = _store()
    semaphore = asyncio.Semaphore(concurrency)

    async def process(document: dict) -> bool:
        async with semaphore:
            try:
                digest = hashlib.sha256()
                size = 0
                media_type = None
                with tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024) as stream:
                    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                        async with client.stream("GET", document["source_url"]) as response:
                            response.raise_for_status()
                            media_type = response.headers.get("content-type", "").split(";", 1)[0] or None
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > settings.bid_document_max_bytes:
                                    raise ValueError("document_size_limit_exceeded")
                                digest.update(chunk)
                                stream.write(chunk)
                    suffix = Path(urlparse(document["source_url"]).path).suffix.lower()
                    file_name = safe_object_file_name(
                        document.get("file_name"), digest.hexdigest(), suffix
                    )
                    object_key = (
                        "public-procurement/bid-notices/"
                        f"{document['notice_number']}/{document['notice_order']}/original/"
                        f"{document['document_id']}/{file_name}"
                    )
                    await asyncio.to_thread(storage.put, object_key, stream, size, media_type)
                store.complete_document(
                    document["document_id"], media_type=media_type, file_size=size,
                    checksum=f"sha256:{digest.hexdigest()}", object_key=object_key,
                )
                return True
            except ValueError as exc:
                unsupported = str(exc) == "document_size_limit_exceeded"
                store.fail_document(document["document_id"], str(exc), unsupported=unsupported)
                return False
            except Exception as exc:
                store.fail_document(document["document_id"], type(exc).__name__)
                return False

    results = await asyncio.gather(*(process(document) for document in documents))
    return LoadSummary(documents=sum(results))


@task(name="보존기간 만료 첨부파일 선택", viz_return_value=[])
def claim_expired_bid_document_objects(retention_days: int,
                                       batch_size: int) -> list[dict]:
    return _store().claim_expired_document_objects(retention_days, batch_size)


@task(name="만료 첨부파일 Object Storage 삭제", retries=1, retry_delay_seconds=60)
def purge_expired_bid_document_objects(documents: list[dict]) -> dict[str, int]:
    if not documents:
        return {"targets": 0, "purged": 0, "objects": 0, "failed": 0}
    storage = _object_storage()
    store = _store()
    purged = deleted_objects = failed = 0
    for document in documents:
        try:
            keys = {document.get("object_key"), document.get("parsed_object_key")} - {None, ""}
            for object_key in keys:
                storage.delete(object_key)
                deleted_objects += 1
            store.complete_document_purge(document["document_id"])
            purged += 1
        except Exception as exc:
            store.fail_document_purge(document["document_id"], type(exc).__name__)
            failed += 1
    return {
        "targets": len(documents), "purged": purged,
        "objects": deleted_objects, "failed": failed,
    }


@task(name="만료 AI 원본 출력 삭제", retries=1, retry_delay_seconds=60)
def purge_expired_eligibility_outputs(retention_days: int, batch_size: int,
                                      document_result: dict[str, int]) -> dict[str, int]:
    storage = _object_storage()
    store = _store()
    deleted = 0
    for extraction in store.list_expired_extraction_objects(retention_days, batch_size):
        storage.delete(extraction["object_key"])
        store.complete_extraction_object_purge(extraction["extraction_id"])
        deleted += 1
    return {**document_result, "objects": document_result["objects"] + deleted}


@task(name="첨부파일 삭제 감사기록 저장")
def record_bid_document_purge(purge_run_id: UUID, retention_days: int,
                              started_at: datetime, result: dict[str, int]) -> LoadSummary:
    _store().record_document_purge_run(
        purge_run_id=purge_run_id,
        retention_days=retention_days,
        target_count=result["targets"],
        purged_count=result["purged"],
        deleted_object_count=result["objects"],
        failed_count=result["failed"],
        started_at=started_at,
    )
    return LoadSummary(documents=result["purged"])
