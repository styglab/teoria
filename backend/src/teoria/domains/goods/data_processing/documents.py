"""Bounded document storage, independent of HTTP request and authorization."""

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from teoria.domains.goods.contracts import SourceDocument
from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store

MAX_DOCUMENT_BYTES = 40 * 1024 * 1024


class DocumentStorageError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def store_document(
    chunks, filename: str, input_root: Path, object_root: str | None
):
    try:
        SourceDocument.safe_filename(filename)
    except ValueError:
        raise DocumentStorageError(422, "unsupported_document_filename") from None
    document_id = "doc_" + uuid4().hex
    digest = hashlib.sha256()
    size = 0

    async def checked_chunks():
        nonlocal size
        async for chunk in chunks:
            size += len(chunk)
            if size > MAX_DOCUMENT_BYTES:
                raise DocumentStorageError(413, "document_size_limit_40mb")
            digest.update(chunk)
            yield chunk
        if size == 0:
            raise DocumentStorageError(422, "empty_document")

    suffix = Path(filename).suffix.lower()
    if object_root and urlsplit(object_root).scheme == "s3":
        data = bytearray()
        async for chunk in checked_chunks():
            data.extend(chunk)
        try:
            async with artifact_store(object_root) as store:
                reference = await store.put(
                    "specification_inputs/" + document_id + suffix,
                    bytes(data),
                    "application/octet-stream",
                )
        except (httpx.HTTPError, ValueError, OSError):
            raise DocumentStorageError(503, "document_storage_unavailable") from None
        source_uri = reference.uri
    else:
        path = input_root / (document_id + suffix)
        stream = None
        try:
            await asyncio.to_thread(input_root.mkdir, parents=True, exist_ok=True)
            stream = await asyncio.to_thread(path.open, "xb")
            async for chunk in checked_chunks():
                await asyncio.to_thread(stream.write, chunk)
            await asyncio.to_thread(stream.close)
            stream = None
        except BaseException:
            if stream is not None:
                await asyncio.to_thread(stream.close)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise
        source_uri = path.as_uri()
    return {
        "document_id": document_id,
        "filename": filename,
        "source_uri": source_uri,
        "sha256": digest.hexdigest(),
    }
