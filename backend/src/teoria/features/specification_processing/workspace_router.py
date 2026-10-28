"""Authenticated document input and read-only processing results for the workspace."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from teoria.features.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.features.specification_processing.models import SourceDocument
from teoria.integrations.data_operations.persistence.connection import connect


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


async def verified_artifact(reference: dict, root: Path) -> dict:
    if reference["size_bytes"] > 5 * 1024 * 1024:
        raise HTTPException(413, "artifact_preview_too_large")
    parsed = urlsplit(reference["uri"])
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise HTTPException(422, "artifact_preview_requires_local_storage")

    def read():
        path = Path(unquote(parsed.path)).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise HTTPException(404, "artifact_not_available")
        with path.open("rb") as stream:
            raw = stream.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(413, "artifact_preview_too_large")
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise HTTPException(409, "artifact_checksum_mismatch")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(422, "artifact_is_not_json") from None

    return await asyncio.to_thread(read)


def create_processing_workspace_router(
    *,
    authorizer: AdminAuthorizer,
    database_url: str | None,
    input_root: Path = Path("/app/specification_inputs"),
    artifact_root: Path = Path("/app/specification_artifacts"),
    repository=None,
    uploads_enabled: bool = False,
):
    router = APIRouter(
        prefix="/v1/admin/specification-processing", tags=["specification-processing"]
    )
    repo = repository or (
        ProcessingWorkspaceRepository(database_url) if database_url else None
    )
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
        path = input_root / (document_id + Path(filename).suffix.lower())
        digest = hashlib.sha256()
        size = 0
        async with upload_slots:
            stream = None
            try:
                await asyncio.to_thread(input_root.mkdir, parents=True, exist_ok=True)
                stream = await asyncio.to_thread(path.open, "xb")
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 40 * 1024 * 1024:
                        raise HTTPException(413, "document_size_limit_40mb")
                    digest.update(chunk)
                    await asyncio.to_thread(stream.write, chunk)
                if size == 0:
                    raise HTTPException(422, "empty_document")
                await asyncio.to_thread(stream.close)
                stream = None
            except BaseException:
                if stream is not None:
                    await asyncio.to_thread(stream.close)
                await asyncio.to_thread(path.unlink, missing_ok=True)
                raise
        logger.info(
            "specification_input_uploaded actor=%s document_id=%s sha256=%s",
            principal.actor,
            document_id,
            digest.hexdigest(),
        )
        return {
            "document_id": document_id,
            "filename": filename,
            "source_uri": path.as_uri(),
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
            return await verified_artifact(reference, artifact_root)

    return router
