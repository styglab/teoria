from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import httpx
from prefect import task

from teoria_pipelines.domains.public_procurement.bid_notices.resources import (
    VIZ_SUMMARY,
    _object_storage,
    _store,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.settings import bootstrap_pipeline_settings


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


@task(name="처리대상 첨부파일 선택", viz_return_value=[])
def claim_bid_documents(batch_size: int = 500) -> list[dict]:
    settings = bootstrap_pipeline_settings()
    return _store().claim_pending_documents(
        batch_size, settings.bid_document_max_attempts
    )


@task(
    name="첨부파일 Object Storage 저장",
    retries=1,
    retry_delay_seconds=60,
    viz_return_value=VIZ_SUMMARY,
)
async def process_bid_documents(
    documents: list[dict], concurrency: int = 8
) -> LoadSummary:
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
                    async with httpx.AsyncClient(
                        timeout=60, follow_redirects=True
                    ) as client:
                        async with client.stream(
                            "GET", document["source_url"]
                        ) as response:
                            response.raise_for_status()
                            media_type = (
                                response.headers.get("content-type", "").split(";", 1)[
                                    0
                                ]
                                or None
                            )
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
                    await asyncio.to_thread(
                        storage.put, object_key, stream, size, media_type
                    )
                store.complete_document(
                    document["document_id"],
                    media_type=media_type,
                    file_size=size,
                    checksum=f"sha256:{digest.hexdigest()}",
                    object_key=object_key,
                )
                return True
            except ValueError as exc:
                unsupported = str(exc) == "document_size_limit_exceeded"
                store.fail_document(
                    document["document_id"], str(exc), unsupported=unsupported
                )
                return False
            except Exception as exc:
                store.fail_document(document["document_id"], type(exc).__name__)
                return False

    results = await asyncio.gather(*(process(document) for document in documents))
    return LoadSummary(documents=sum(results))
