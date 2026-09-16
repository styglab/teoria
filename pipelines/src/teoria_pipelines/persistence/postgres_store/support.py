from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import re
from psycopg.types.json import Jsonb

from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    LoadSummary,
    NormalizedBatch,
    NormalizedBidResultBatch,
    NormalizedBidNoticeBatch,
    RawProviderRecord,
)


def eligibility_requires_review(notice: dict[str, Any], result: dict[str, Any]) -> bool:
    return (
        notice["coverage"]["requires_review"]
        or any(item.get("blocks_qualification", True)
               for item in result["unresolved_candidates"])
        or any(item["review_status"] == "needs_review" for item in result["requirements"])
        or any(item.get("failure_effect") == "needs_review" for item in result["requirements"])
        or any(
            proof["review_status"] == "needs_review"
            for item in result["requirements"]
            for proof in item.get("proof_requirements", [])
        )
    )


def _validate_industry_snapshot(rows: list[dict[str, Any]], previous_active_count: int) -> None:
    if not rows:
        raise ValueError("empty_industry_snapshot")
    codes = [str(row.get("industry_code") or "") for row in rows]
    if any(not code or not row.get("industry_name") or not row.get("classification_code")
           or not row.get("classification_name") or not row.get("source_registered_at")
           for code, row in zip(codes, rows, strict=True)):
        raise ValueError("invalid_industry_snapshot_required_field")
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate_industry_code_in_snapshot")
    if previous_active_count and len(rows) < previous_active_count * 0.9:
        raise ValueError("industry_snapshot_count_dropped_over_10_percent")


def _document_stem(file_name: str | None) -> str:
    return Path(str(file_name or "").strip()).stem.casefold()


def _filter_covered_unavailable_documents(
    documents: list[tuple], unavailable_documents: list[tuple]
) -> list[tuple]:
    """Drop failed source-format copies when an equivalent rendition parsed."""
    covered_checksums = {row[2] for row in documents if row[2]}
    covered_stems = {_document_stem(row[1]) for row in documents if _document_stem(row[1])}
    remaining = list(unavailable_documents)
    while True:
        retained = []
        changed = False
        for row in remaining:
            checksum = row[8]
            stem = _document_stem(row[1])
            if (checksum and checksum in covered_checksums) or (stem and stem in covered_stems):
                if checksum:
                    covered_checksums.add(checksum)
                if stem:
                    covered_stems.add(stem)
                changed = True
            else:
                retained.append(row)
        remaining = retained
        if not changed:
            return remaining


def _sanitize_postgres_value(value: Any) -> Any:
    """Recursively remove NUL characters unsupported by PostgreSQL text/jsonb."""
    if isinstance(value, str):
        return value.replace("\x00", " ")
    if isinstance(value, dict):
        return {key: _sanitize_postgres_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_postgres_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_postgres_value(item) for item in value)
    return value



