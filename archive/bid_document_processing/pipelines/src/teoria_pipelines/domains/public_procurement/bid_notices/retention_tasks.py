from __future__ import annotations

from datetime import datetime
from uuid import UUID

from prefect import task

from teoria_pipelines.domains.public_procurement.bid_notices.resources import (
    _object_storage,
    _store,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary


@task(name="보존기간 만료 첨부파일 선택", viz_return_value=[])
def claim_expired_bid_document_objects(
    retention_days: int, batch_size: int
) -> list[dict]:
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
            keys = {document.get("object_key"), document.get("parsed_object_key")} - {
                None,
                "",
            }
            for object_key in keys:
                storage.delete(object_key)
                deleted_objects += 1
            store.complete_document_purge(document["document_id"])
            purged += 1
        except Exception as exc:
            store.fail_document_purge(document["document_id"], type(exc).__name__)
            failed += 1
    return {
        "targets": len(documents),
        "purged": purged,
        "objects": deleted_objects,
        "failed": failed,
    }


@task(name="만료 AI 원본 출력 삭제", retries=1, retry_delay_seconds=60)
def purge_expired_eligibility_outputs(
    retention_days: int, batch_size: int, document_result: dict[str, int]
) -> dict[str, int]:
    storage = _object_storage()
    store = _store()
    deleted = 0
    for extraction in store.list_expired_extraction_objects(retention_days, batch_size):
        storage.delete(extraction["object_key"])
        store.complete_extraction_object_purge(extraction["extraction_id"])
        deleted += 1
    return {**document_result, "objects": document_result["objects"] + deleted}


@task(name="첨부파일 삭제 감사기록 저장")
def record_bid_document_purge(
    purge_run_id: UUID,
    retention_days: int,
    started_at: datetime,
    result: dict[str, int],
) -> LoadSummary:
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
