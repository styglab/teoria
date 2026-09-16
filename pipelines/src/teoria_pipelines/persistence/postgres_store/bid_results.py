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

from teoria_pipelines.persistence.postgres_store.support import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    _validate_industry_snapshot,
    eligibility_requires_review,
)


class BidResultStoreMixin:
    """bid results persistence operations."""

    def upsert_bid_results(self, batch: NormalizedBidResultBatch) -> LoadSummary:
        with psycopg.connect(self.database_url) as connection:
            self._upsert_many(
                connection,
                "public_procurement.bid_awards",
                batch.awards,
                ("notice_number", "notice_order", "bid_classification_number", "rebid_number"),
            )
            self._upsert_many(
                connection,
                "public_procurement.bid_opening_participants",
                batch.opening_participants,
                (
                    "notice_number", "notice_order", "bid_classification_number",
                    "rebid_number", "business_registration_number",
                ),
            )
        return LoadSummary(
            awards=len(batch.awards),
            opening_participants=len(batch.opening_participants),
        )

    def select_bid_awards_for_opening(
        self, records: Iterable[RawProviderRecord]
    ) -> list[RawProviderRecord]:
        awards: dict[tuple[str, str, str, str], RawProviderRecord] = {}
        for record in records:
            if not record.operation_id.startswith("list_") or record.operation_id == "list_completed_opening_results":
                continue
            key = tuple(str(record.payload.get(name) or "").strip() for name in (
                "bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo"
            ))
            if key[0]:
                awards[key] = record
        if not awards:
            return []
        keys = list(awards)
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT notice_number,notice_order,bid_classification_number,rebid_number,"
                "award_source_record_hash FROM ingestion.bid_opening_collection_status "
                "WHERE (notice_number,notice_order,bid_classification_number,rebid_number) IN "
                "(SELECT * FROM unnest(%s::text[],%s::text[],%s::text[],%s::text[]))",
                tuple([key[index] for key in keys] for index in range(4)),
            ).fetchall()
        checked = {(row[0], row[1], row[2], row[3]): row[4] for row in rows}
        return [record for key, record in awards.items()
                if checked.get(key) != record.source_record_hash]

    def mark_bid_openings_checked(
        self, awards: Iterable[RawProviderRecord], participants: Iterable[RawProviderRecord],
        execution_id: UUID,
    ) -> int:
        counts: dict[tuple[str, str, str, str], int] = {}
        for record in participants:
            key = tuple(str(record.payload.get(name) or "").strip() for name in (
                "bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo"
            ))
            counts[key] = counts.get(key, 0) + 1
        values = []
        for record in awards:
            key = tuple(str(record.payload.get(name) or "").strip() for name in (
                "bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo"
            ))
            values.append((*key, record.source_record_hash, counts.get(key, 0), execution_id))
        if not values:
            return 0
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO ingestion.bid_opening_collection_status "
                    "(notice_number,notice_order,bid_classification_number,rebid_number,"
                    "award_source_record_hash,participant_count,execution_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
                    "(notice_number,notice_order,bid_classification_number,rebid_number) "
                    "DO UPDATE SET award_source_record_hash=EXCLUDED.award_source_record_hash,"
                    "participant_count=EXCLUDED.participant_count,execution_id=EXCLUDED.execution_id,"
                    "checked_at=now()",
                    values,
                )
        return len(values)

    def replace_bid_opening_participants(
        self, awards: Iterable[RawProviderRecord], batch: NormalizedBidResultBatch
    ) -> LoadSummary:
        keys = [tuple(str(record.payload.get(name) or "").strip() for name in (
            "bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo"
        )) for record in awards]
        with psycopg.connect(self.database_url) as connection:
            if keys:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "DELETE FROM public_procurement.bid_opening_participants "
                        "WHERE notice_number=%s AND notice_order=%s "
                        "AND bid_classification_number=%s AND rebid_number=%s",
                        keys,
                    )
            self._upsert_many(
                connection,
                "public_procurement.bid_opening_participants",
                batch.opening_participants,
                (
                    "notice_number", "notice_order", "bid_classification_number",
                    "rebid_number", "business_registration_number",
                ),
            )
        return LoadSummary(opening_participants=len(batch.opening_participants))

