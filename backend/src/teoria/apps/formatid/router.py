"""Authenticated document input and read-only processing results for the workspace."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from datetime import date
from typing import Literal
from teoria.domains.goods.data_processing.queries import ProcessingQueries
from teoria.domains.goods.data_processing.catalog.results import document_result
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from teoria.platform.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.domains.goods.contracts import SourceDocument
from teoria.domains.goods.data_processing.documents import (
    store_document,
    DocumentStorageError,
)
from teoria.domains.goods.data_processing.storage.artifact_reader import (
    verified_artifact as read_artifact,
    ArtifactReadError,
)


logger = logging.getLogger(__name__)


async def verified_artifact(*args, **kwargs):
    try:
        return await read_artifact(*args, **kwargs)
    except ArtifactReadError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None


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
    queries = ProcessingQueries(database_url) if database_url else None
    repo = repository or queries
    object_root = object_root or os.getenv(
        "TEORIA_SPECIFICATION_ARTIFACT_ROOT", "s3://teoria-artifacts"
    )
    if (
        os.getenv("TEORIA_SPECIFICATION_REQUIRE_OBJECT_STORAGE") == "true"
        and urlsplit(object_root).scheme != "s3"
    ):
        raise ValueError("production specification storage requires an S3 root")
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
        async with upload_slots:
            try:
                document = await store_document(
                    request.stream(), filename, input_root, object_root
                )
            except DocumentStorageError as exc:
                raise HTTPException(exc.status_code, exc.detail) from None
        logger.info(
            "specification_input_uploaded actor=%s document_id=%s sha256=%s",
            principal.actor,
            document["document_id"],
            document["sha256"],
        )
        return document

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

    @router.get("/operations")
    async def operations(
        days: int = Query(7, ge=1, le=90),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        if repo is None:
            raise HTTPException(503, "processing_database_not_configured")
        try:
            return await repo.operations(days)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None

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

    @router.get("/runs/{run_id}/inputs")
    async def replay_inputs(
        run_id: str,
        failed_only: bool = False,
        principal: AdminPrincipal = Depends(authorizer.require("metadata_admin")),
    ):
        result = await detail(run_id, principal)
        if result["run"].get("status") not in {"completed", "partial", "failed"}:
            raise HTTPException(409, "processing_run_not_finished")
        try:
            documents = await repo.inputs(run_id)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None
        if not documents:
            raise HTTPException(409, "processing_inputs_not_available")
        if failed_only:
            failed_ids = {
                d["document_id"]
                for d in result["documents"]
                if d["status"] == "failed"
                or d.get("result_summary", {}).get("quarantined_attributes", 0) > 0
            }
            documents = [d for d in documents if d["document_id"] in failed_ids]
            if not documents:
                raise HTTPException(409, "no_failed_documents_to_retry")
        try:
            if any(not d.get("sha256") for d in documents):
                raise ValueError("verified source hash required")
            documents = [
                SourceDocument.model_validate(d).model_dump(mode="json")
                for d in documents
            ]
        except ValueError:
            raise HTTPException(
                409, "processing_inputs_incomplete_register_originals_again"
            ) from None
        return {
            "source_run_id": run_id,
            "documents": documents,
            "classification_code": result["run"].get("classification_code"),
        }

    catalog = queries.catalog if queries else None

    async def catalog_call(method, *args, **kwargs):
        if catalog is None:
            raise HTTPException(503, "processing_database_not_configured")
        try:
            return await getattr(catalog, method)(*args, **kwargs)
        except psycopg.Error:
            raise HTTPException(503, "processing_results_unavailable") from None

    @router.get("/catalog/classifications")
    async def classifications(
        query: str = Query("", max_length=100),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await catalog_call(
            "classifications", query=query, offset=offset, limit=limit
        )

    @router.get("/catalog/documents")
    async def documents(
        classification: str = Query("", pattern=r"^(?:[0-9]{10}|unclassified)?$"),
        query: str = Query("", max_length=200),
        status: Literal[
            "all", "running", "extracted", "partial", "failed", "excluded"
        ] = "all",
        since: date | None = None,
        until: date | None = None,
        sort: Literal["recent", "name"] = "recent",
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        if since and until and since > until:
            raise HTTPException(422, "invalid_date_range")
        return await catalog_call(
            "documents",
            classification=classification,
            query=query,
            status=status,
            since=since,
            until=until,
            sort=sort,
            offset=offset,
            limit=limit,
        )

    @router.get("/catalog/documents/{catalog_id}/history")
    async def history(
        catalog_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(25, ge=1, le=100),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        if not await catalog_call("entry", catalog_id):
            raise HTTPException(404, "document_not_found")
        return await catalog_call("history", catalog_id, offset=offset, limit=limit)

    @router.get("/catalog/documents/{catalog_id}/result")
    async def result(
        catalog_id: str, principal: AdminPrincipal = Depends(authorizer.require())
    ):
        entry = await catalog_call("entry", catalog_id)
        if not entry:
            raise HTTPException(404, "document_not_found")
        if not entry["result_available"]:
            return {"document": entry, "result": None}
        run = await detail(entry["run_id"], principal)
        key = f"specification_processing/{entry['run_id']}/documents/{entry['document_id']}/result.json"
        ref = next((r for r in run["artifacts"] if r["key"] == key), None)
        async with preview_slots:
            if ref:
                payload = await verified_artifact(ref, artifact_root, object_root)
                if (
                    payload.get("artifact_kind") != "specification_document_result"
                    or payload.get("document_id") != entry["document_id"]
                    or payload.get("source_sha256") != entry["source_sha256"]
                ):
                    raise HTTPException(409, "document_result_identity_mismatch")
            else:
                extracted = next(
                    (
                        r
                        for r in run["artifacts"]
                        if r["key"].endswith("/extracted.json")
                        or r["key"] == "extracted.json"
                    ),
                    None,
                )
                normalized = next(
                    (
                        r
                        for r in run["artifacts"]
                        if r["key"].endswith("/normalized.json")
                    ),
                    None,
                )
                if not extracted:
                    raise HTTPException(404, "artifact_not_found")
                corpus = await verified_artifact(extracted, artifact_root, object_root)
                norm = (
                    await verified_artifact(normalized, artifact_root, object_root)
                    if normalized
                    else None
                )
                try:
                    payload = document_result(corpus, norm, entry["document_id"])
                except (KeyError, ValueError):
                    raise HTTPException(409, "invalid_document_result") from None
        return {"document": entry, "result": payload}

    @router.get("/runs/{run_id}/validation/{document_id}/{attribute_id}")
    async def reproduce_validation(
        run_id: str,
        document_id: str,
        attribute_id: str,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        from teoria.domains.goods.data_processing.extraction.extraction_validation import (
            reproduce_attribute_validation,
        )

        run = await detail(run_id, principal)
        key = f"specification_processing/{run_id}/documents/{document_id}/result.json"
        ref = next((a for a in run["artifacts"] if a["key"] == key), None)
        if ref is None:
            raise HTTPException(404, "document_result_not_found")
        async with preview_slots:
            payload = await verified_artifact(ref, artifact_root, object_root)
            if payload.get("document_id") != document_id:
                raise HTTPException(409, "document_result_identity_mismatch")
            document = next(
                (
                    d
                    for d in payload.get("extracted", {}).get("documents", [])
                    if d["document_id"] == document_id
                ),
                None,
            )
            if document is None:
                raise HTTPException(404, "extracted_document_not_found")
            try:
                return await asyncio.to_thread(
                    reproduce_attribute_validation, document, attribute_id
                )
            except KeyError:
                raise HTTPException(404, "attribute_not_found") from None

    return router
