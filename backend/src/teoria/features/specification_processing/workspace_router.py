"""Authenticated document input and read-only processing results for the workspace."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import httpx
from pathlib import Path
from datetime import date
from typing import Literal
from teoria.features.specification_processing.catalog.repository import DocumentCatalogRepository
from teoria.features.specification_processing.catalog.results import document_result
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.specification_processing.models import SourceDocument
from teoria.integrations.data_operations.persistence.connection import connect
from teoria.features.specification_processing.storage.artifact_store import artifact_store, object_key


logger = logging.getLogger(__name__)


class ProcessingWorkspaceRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def runs(self, offset: int, limit: int):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    """SELECT run_id,mode,classification_code,status,summary,error_code,started_at,finished_at
                FROM public_procurement.specification_processing_runs ORDER BY started_at DESC,run_id LIMIT %s OFFSET %s""",
                    (limit, offset),
                )
            ).fetchall()
            total = await (
                await conn.execute(
                    "SELECT count(*) AS total FROM public_procurement.specification_processing_runs"
                )
            ).fetchone()
            return {"items": rows, "total": total["total"]}

    async def detail(self, run_id: str):
        async with connect(self.database_url, row_factory=dict_row) as conn:
            row = await (
                await conn.execute(
                    """SELECT run_id,mode,classification_code,status,summary,error_code,started_at,finished_at,
                standard_uri,standard_sha256 FROM public_procurement.specification_processing_runs WHERE run_id=%s""",
                    (run_id,),
                )
            ).fetchone()
            if row is None:
                return None
            documents = await (
                await conn.execute(
                    """SELECT document_id,status,source_sha256,result_summary FROM
                public_procurement.specification_processing_documents WHERE run_id=%s ORDER BY document_id""",
                    (run_id,),
                )
            ).fetchall()
            artifacts = await (
                await conn.execute(
                    """SELECT object_key AS key,uri,sha256,size_bytes,media_type FROM
                public_procurement.specification_processing_artifacts WHERE run_id=%s ORDER BY object_key""",
                    (run_id,),
                )
            ).fetchall()
            return {"run": row, "documents": documents, "artifacts": artifacts}


async def verified_artifact(reference: dict, root: Path, object_root: str | None = None, *, limit: int = 5*1024*1024) -> dict:
    if reference['size_bytes']>limit:raise HTTPException(413,'artifact_preview_too_large')
    uri=reference['uri'];parsed=urlsplit(uri)
    if parsed.scheme=='file':
        path=Path(unquote(parsed.path)).resolve()
        if parsed.netloc not in {'','localhost'} or not path.is_relative_to(root.resolve()):
            raise HTTPException(404,'artifact_not_available')
    try:
        if parsed.scheme=='s3':
            trusted=urlsplit(object_root or '')
            prefix=trusted.path.strip('/')
            key=parsed.path.lstrip('/')
            if trusted.scheme!='s3' or trusted.netloc!=parsed.netloc or (prefix and not key.startswith(prefix+'/')):
                raise HTTPException(404,'artifact_not_available')
            relative=key[len(prefix)+1:] if prefix else key
            try:object_key(relative)
            except ValueError:raise HTTPException(404,'artifact_not_available') from None
            async with artifact_store(object_root) as store:
                raw=await store.get(relative,max_bytes=limit)
        elif parsed.scheme=='file':
            def read():
                if not path.is_file():raise FileNotFoundError(path)
                with path.open('rb') as stream:return stream.read(limit+1)
            raw=await asyncio.to_thread(read)
        else:raise HTTPException(422,'unsupported_artifact_storage')
    except FileNotFoundError:raise HTTPException(404,'artifact_not_available') from None
    except httpx.HTTPError:raise HTTPException(503,'artifact_storage_unavailable') from None
    except ValueError:raise HTTPException(413,'artifact_preview_too_large') from None
    if len(raw)>limit:raise HTTPException(413,'artifact_preview_too_large')
    if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise HTTPException(409,'artifact_checksum_mismatch')
    try:return json.loads(raw)
    except (ValueError,UnicodeError):raise HTTPException(422,'artifact_is_not_json') from None


def create_processing_workspace_router(
    *,
    authorizer: AdminAuthorizer,
    database_url: str | None,
    input_root: Path = Path("/app/specification_inputs"),
    artifact_root: Path = Path("/app/specification_artifacts"),
    repository=None,
    object_root: str | None = None,
    uploads_enabled: bool = False,
):
    router = APIRouter(
        prefix="/v1/admin/specification-processing", tags=["specification-processing"]
    )
    repo = repository or (
        ProcessingWorkspaceRepository(database_url) if database_url else None
    )
    object_root = object_root or os.getenv("TEORIA_SPECIFICATION_ARTIFACT_ROOT",'s3://teoria-artifacts')
    if os.getenv('TEORIA_SPECIFICATION_REQUIRE_OBJECT_STORAGE')=='true' and urlsplit(object_root).scheme!='s3':
        raise ValueError('production specification storage requires an S3 root')
    upload_slots = asyncio.Semaphore(2)
    preview_slots = asyncio.Semaphore(4)

    @router.get("/status")
    async def status(principal: AdminPrincipal = Depends(authorizer.require())):
        return {"uploads_enabled": uploads_enabled, "results_enabled": repo is not None}

    @router.post("/documents", status_code=201)
    async def upload(
        request: Request,
        filename: str = Query(min_length=1, max_length=200),
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        if not uploads_enabled:
            raise HTTPException(503, "document_upload_not_configured")
        try:
            SourceDocument.safe_filename(filename)
        except ValueError:
            raise HTTPException(422, "unsupported_document_filename") from None
        document_id = "doc_" + uuid4().hex
        digest = hashlib.sha256()
        size = 0
        async with upload_slots:
            if object_root and urlsplit(object_root).scheme=='s3':
                data=bytearray()
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>40*1024*1024:raise HTTPException(413,'document_size_limit_40mb')
                    digest.update(chunk);data.extend(chunk)
                if not data:raise HTTPException(422,'empty_document')
                key='specification_inputs/'+document_id+Path(filename).suffix.lower()
                try:
                    async with artifact_store(object_root) as store:
                        reference=await store.put(key,bytes(data),'application/octet-stream')
                except (httpx.HTTPError,ValueError,OSError):
                    raise HTTPException(503,'document_storage_unavailable') from None
                source_uri=reference.uri
            else:
                path = input_root / (document_id + Path(filename).suffix.lower())
                stream = None
                try:
                    await asyncio.to_thread(input_root.mkdir, parents=True, exist_ok=True)
                    stream = await asyncio.to_thread(path.open, 'xb')
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 40 * 1024 * 1024:raise HTTPException(413,'document_size_limit_40mb')
                        digest.update(chunk)
                        await asyncio.to_thread(stream.write, chunk)
                    if size == 0:raise HTTPException(422,'empty_document')
                    await asyncio.to_thread(stream.close);stream = None
                except BaseException:
                    if stream is not None:await asyncio.to_thread(stream.close)
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                    raise
                source_uri=path.as_uri()
        logger.info(
            "specification_input_uploaded actor=%s document_id=%s sha256=%s",
            principal.actor,
            document_id,
            digest.hexdigest(),
        )
        return {
            "document_id": document_id,
            "filename": filename,
            "source_uri": source_uri,
            "sha256": digest.hexdigest(),
        }

    @router.get("/runs")
    async def runs(
        offset: int = Query(0, ge=0, le=100000),
        limit: int = Query(25, ge=1, le=50),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        if repo is None:
            raise HTTPException(503, "processing_database_not_configured")
        try:
            return await repo.runs(offset, limit)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None

    @router.get("/runs/{run_id}")
    async def detail(
        run_id: str, principal: AdminPrincipal = Depends(authorizer.require())
    ):
        if repo is None:
            raise HTTPException(503, "processing_database_not_configured")
        try:
            result = await repo.detail(run_id)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None
        if result is None:
            raise HTTPException(404, "processing_run_not_found")
        return result

    @router.get("/runs/{run_id}/artifact")
    async def artifact(
        run_id: str, key: str, principal: AdminPrincipal = Depends(authorizer.require())
    ):
        result = await detail(run_id, principal)
        reference = next(
            (ref for ref in result["artifacts"] if ref["key"] == key), None
        )
        if reference is None:
            raise HTTPException(404, "artifact_not_found")
        async with preview_slots:
            return await verified_artifact(reference, artifact_root, object_root)

    catalog = DocumentCatalogRepository(database_url) if database_url else None

    async def catalog_call(method, *args, **kwargs):
        if catalog is None:
            raise HTTPException(503, "processing_database_not_configured")
        try:
            return await getattr(catalog, method)(*args, **kwargs)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None

    @router.get("/catalog/classifications")
    async def classifications(query: str = Query("", max_length=100), offset: int = Query(0, ge=0),
                              limit: int = Query(100, ge=1, le=100),
                              principal: AdminPrincipal = Depends(authorizer.require())):
        return await catalog_call("classifications", query=query, offset=offset, limit=limit)

    @router.get("/catalog/documents")
    async def documents(classification: str = Query("", pattern=r"^(?:[0-9]{10}|unclassified)?$"),
                        query: str = Query("", max_length=200),
                        status: Literal["all", "running", "extracted", "partial", "failed", "excluded"] = "all",
                        since: date | None = None, until: date | None = None,
                        sort: Literal["recent", "name"] = "recent", offset: int = Query(0, ge=0),
                        limit: int = Query(25, ge=1, le=100),
                        principal: AdminPrincipal = Depends(authorizer.require())):
        if since and until and since > until:
            raise HTTPException(422, "invalid_date_range")
        return await catalog_call("documents", classification=classification, query=query, status=status,
                                  since=since, until=until, sort=sort, offset=offset, limit=limit)

    @router.get("/catalog/documents/{catalog_id}/history")
    async def history(catalog_id: str, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
                      principal: AdminPrincipal = Depends(authorizer.require())):
        if not await catalog_call("entry", catalog_id):
            raise HTTPException(404, "document_not_found")
        return await catalog_call("history", catalog_id, offset=offset, limit=limit)

    @router.get("/catalog/documents/{catalog_id}/result")
    async def result(catalog_id: str, principal: AdminPrincipal = Depends(authorizer.require())):
        entry = await catalog_call("entry", catalog_id)
        if not entry:
            raise HTTPException(404, "document_not_found")
        if not entry['result_available']:
            return {"document": entry, "result": None}
        run = await detail(entry['run_id'], principal)
        key = f"specification_processing/{entry['run_id']}/documents/{entry['document_id']}/result.json"
        ref = next((r for r in run['artifacts'] if r['key'] == key), None)
        async with preview_slots:
            if ref:
                payload = await verified_artifact(ref, artifact_root, object_root)
                if payload.get('artifact_kind') != 'specification_document_result' or payload.get('document_id') != entry['document_id'] or payload.get('source_sha256') != entry['source_sha256']:
                    raise HTTPException(409, 'document_result_identity_mismatch')
            else:
                extracted = next((r for r in run['artifacts'] if r['key'].endswith('/extracted.json') or r['key']=='extracted.json'), None)
                normalized = next((r for r in run['artifacts'] if r['key'].endswith('/normalized.json')), None)
                if not extracted:
                    raise HTTPException(404, 'artifact_not_found')
                corpus = await verified_artifact(extracted, artifact_root, object_root)
                norm = await verified_artifact(normalized, artifact_root, object_root) if normalized else None
                try:
                    payload = document_result(corpus, norm, entry['document_id'])
                except (KeyError, ValueError):
                    raise HTTPException(409, 'invalid_document_result') from None
        return {"document": entry, "result": payload}

    return router
