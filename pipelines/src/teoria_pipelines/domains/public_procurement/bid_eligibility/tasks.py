from __future__ import annotations

import asyncio
import json
import subprocess

from prefect import task

from teoria_pipelines.domains.public_procurement.bid_eligibility.documents import (
    PARSER_VERSION,
    UnsupportedDocumentError,
    parse_document,
)
from teoria_pipelines.domains.public_procurement.bid_eligibility.extraction import (
    EXTRACTION_VERSION,
    _input_fingerprint,
    extract_notice,
    normalize_structured_notice,
)
from teoria_pipelines.domains.public_procurement.bid_eligibility.resources import _resources
from teoria_pipelines.models import LoadSummary
from teoria_pipelines.settings import bootstrap_pipeline_settings


def _ensure_codex_authenticated() -> None:
    process = subprocess.run(
        ["codex", "login", "status"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(
            "Codex ChatGPT login is required. Run "
            "`docker compose --env-file deploy/compose/.env "
            "-f deploy/compose/compose.yaml exec "
            "prefect-ai-worker codex login --device-auth`."
        )


@task(name="문서 파싱 대상 선택", viz_return_value=[])
def claim_documents_for_parsing(batch_size: int = 100) -> list[dict]:
    settings = bootstrap_pipeline_settings()
    return _resources()[0].claim_documents_for_parsing(
        batch_size, PARSER_VERSION, settings.bid_document_parse_max_attempts
    )


@task(name="입찰문서 구조 파싱", retries=1, retry_delay_seconds=60,
      viz_return_value=LoadSummary())
async def parse_bid_documents(documents: list[dict], concurrency: int = 4) -> LoadSummary:
    store, storage = _resources()
    semaphore = asyncio.Semaphore(concurrency)

    async def process(document: dict) -> bool:
        async with semaphore:
            try:
                source = await asyncio.to_thread(storage.get_bytes, document["object_key"])
                parser_name, parsed = await asyncio.to_thread(
                    parse_document, source, document["file_name"], document["media_type"]
                )
                parsed.update({
                    "document_id": str(document["document_id"]),
                    "notice_number": document["notice_number"],
                    "notice_order": document["notice_order"],
                    "source_checksum": document["checksum"],
                    "parser_name": parser_name,
                    "parser_version": PARSER_VERSION,
                })
                key = (f"public-procurement/bid-notices/{document['notice_number']}/"
                       f"{document['notice_order']}/parsed/{document['document_id']}/"
                       f"{PARSER_VERSION}/document.json")
                encoded = json.dumps(parsed, ensure_ascii=False).encode()
                await asyncio.to_thread(storage.put_bytes, key, encoded, "application/json")
                store.complete_document_parse(document["document_id"], parser_name=parser_name,
                                              parser_version=PARSER_VERSION, parsed_object_key=key)
                return True
            except UnsupportedDocumentError as exc:
                store.fail_document_parse(
                    document["document_id"], str(exc), parser_version=PARSER_VERSION,
                    unsupported=True,
                )
                return False
            except Exception as exc:
                store.fail_document_parse(document["document_id"], type(exc).__name__)
                return False

    results = await asyncio.gather(*(process(document) for document in documents))
    return LoadSummary(documents=sum(results))


@task(name="요건 추출 대상 공고 선택", viz_return_value=[])
def select_notices_for_extraction(batch_size: int = 20) -> list[dict]:
    settings = bootstrap_pipeline_settings()
    store = _resources()[0]
    candidates = store.list_notices_for_eligibility_extraction(
        max(1000, batch_size),
        settings.bid_document_max_attempts,
        settings.bid_document_parse_max_attempts,
    )
    completed = store.completed_eligibility_fingerprints()
    selected = []
    for notice in candidates:
        fingerprint = _input_fingerprint(notice)
        if fingerprint in completed:
            continue
        if store.claim_eligibility_extraction(notice, fingerprint, EXTRACTION_VERSION):
            selected.append(notice)
        if len(selected) == batch_size:
            break
    return selected


@task(name="Codex 인증 확인")
def ensure_codex_authentication() -> None:
    _ensure_codex_authenticated()


@task(name="공고별 API 참가자격 정규화", retries=2, retry_delay_seconds=30,
      task_run_name="API 참가자격 정규화 {notice[notice_number]}:{notice[notice_order]}")
def normalize_structured_bid_eligibility_notice(notice: dict) -> bool:
    return normalize_structured_notice(notice)


@task(name="공고별 Codex 참가자격 추출",
      task_run_name="참가자격 추출 {notice[notice_number]}:{notice[notice_order]}")
async def extract_bid_eligibility_notice(
    notice: dict, *, persist: bool = True, include_evaluation_input: bool = False,
) -> bool | dict:
    return await extract_notice(
        notice, persist=persist, include_evaluation_input=include_evaluation_input,
    )
