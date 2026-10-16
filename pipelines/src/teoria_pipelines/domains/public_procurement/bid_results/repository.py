from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from teoria_pipelines.persistence.connection import connect

from teoria_pipelines.domains.public_procurement.bid_results.models import (
    NormalizedBidResultBatch,
)
from teoria_pipelines.domains.public_procurement.bid_results.selection import (
    select_participants,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.domains.public_procurement.repository import (
    ProcurementRunRepository,
)
from teoria_pipelines.models import CollectionWindow, ExtractedBatch, RawProviderRecord


class BidResultRepository(ProcurementRunRepository):
    """bid results persistence operations."""

    async def upsert_bid_results(self, batch: NormalizedBidResultBatch) -> LoadSummary:
        async with connect(self.database_url) as connection:
            await self._upsert_many(
                connection,
                "public_procurement.bid_awards",
                batch.awards,
                (
                    "notice_number",
                    "notice_order",
                    "bid_classification_number",
                    "rebid_number",
                ),
            )
            await self._upsert_many(
                connection,
                "public_procurement.bid_opening_participants",
                batch.opening_participants,
                (
                    "notice_number",
                    "notice_order",
                    "bid_classification_number",
                    "rebid_number",
                    "business_registration_number",
                ),
            )
            await self._upsert_many(
                connection,
                "public_procurement.bid_notice_outcomes",
                batch.notice_outcomes,
                (
                    "notice_number",
                    "notice_order",
                    "bid_classification_number",
                    "rebid_number",
                ),
            )
        return LoadSummary(
            awards=len(batch.awards),
            opening_participants=len(batch.opening_participants),
            notice_outcomes=len(batch.notice_outcomes),
        )

    async def select_pending_bid_notice_outcomes(
        self,
        execution_id: UUID,
        limit: int,
    ) -> list[RawProviderRecord]:
        now = datetime.now(timezone.utc)
        async with connect(self.database_url) as connection:
            rows = await (
                await connection.execute(
                    "SELECT n.notice_number,n.source_record_hash "
                    "FROM public_procurement.bid_notice_latest_versions latest "
                    "JOIN public_procurement.bid_notices n "
                    "ON n.notice_number=latest.notice_number "
                    "AND n.notice_order=latest.notice_order "
                    "LEFT JOIN ingestion.bid_notice_outcome_collection_status checked "
                    "ON checked.notice_number=n.notice_number "
                    "WHERE n.opening_at<now() AND n.opening_at>=now()-interval '5 years' "
                    "AND n.notice_kind_name<>'취소공고' "
                    "AND NOT EXISTS (SELECT 1 FROM public_procurement.bid_awards award "
                    "WHERE award.notice_number=n.notice_number) "
                    "AND (checked.notice_number IS NULL OR "
                    "checked.notice_source_record_hash<>n.source_record_hash) "
                    "ORDER BY n.opening_at DESC NULLS LAST,n.notice_number DESC LIMIT %s",
                    (limit,),
                )
            ).fetchall()
        today = now.date()
        return [
            RawProviderRecord(
                raw_record_id=uuid4(),
                execution_id=execution_id,
                connector_id="pps_bid_result_api",
                operation_id="list_failing_opening_results",
                window=CollectionWindow(today, today),
                fetched_at=now,
                source_record_hash=source_record_hash,
                payload={"bidNtceNo": notice_number},
            )
            for notice_number, source_record_hash in rows
        ]

    async def mark_bid_notice_outcomes_checked(
        self,
        notices: Iterable[RawProviderRecord],
        outcomes: Iterable[RawProviderRecord],
    ) -> int:
        counts: dict[str, int] = {}
        for record in outcomes:
            notice_number = str(record.payload.get("bidNtceNo") or "").strip()
            counts[notice_number] = counts.get(notice_number, 0) + 1
        values = [
            (
                str(record.payload.get("bidNtceNo") or "").strip(),
                record.source_record_hash,
                counts.get(str(record.payload.get("bidNtceNo") or "").strip(), 0),
            )
            for record in notices
            if str(record.payload.get("bidNtceNo") or "").strip()
        ]
        if not values:
            return 0
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO ingestion.bid_notice_outcome_collection_status "
                    "(notice_number,notice_source_record_hash,outcome_count) "
                    "VALUES (%s,%s,%s) ON CONFLICT (notice_number) DO UPDATE SET "
                    "notice_source_record_hash=EXCLUDED.notice_source_record_hash,"
                    "outcome_count=EXCLUDED.outcome_count,checked_at=now()",
                    values,
                )
        return len(values)

    async def select_bid_awards_for_opening(
        self, records: Iterable[RawProviderRecord]
    ) -> list[RawProviderRecord]:
        awards: dict[tuple[str, str, str, str], RawProviderRecord] = {}
        for record in records:
            if (
                not record.operation_id.startswith("list_")
                or record.operation_id == "list_completed_opening_results"
            ):
                continue
            key = tuple(
                str(record.payload.get(name) or "").strip()
                for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
            )
            if key[0]:
                awards[key] = record
        if not awards:
            return []
        keys = list(awards)
        async with connect(self.database_url) as connection:
            rows = await (
                await connection.execute(
                    "SELECT notice_number,notice_order,bid_classification_number,rebid_number,"
                    "award_source_record_hash FROM ingestion.bid_opening_collection_status "
                    "WHERE (notice_number,notice_order,bid_classification_number,rebid_number) IN "
                    "(SELECT * FROM unnest(%s::text[],%s::text[],%s::text[],%s::text[]))",
                    tuple([key[index] for key in keys] for index in range(4)),
                )
            ).fetchall()
        checked = {(row[0], row[1], row[2], row[3]): row[4] for row in rows}
        return [
            record
            for key, record in awards.items()
            if checked.get(key) != record.source_record_hash
        ]

    async def enqueue_bid_opening_enrichment(
        self, records: Iterable[RawProviderRecord], queue_class: str = "backfill"
    ) -> int:
        if queue_class not in {"incremental", "backfill"}:
            raise ValueError("queue_class must be incremental or backfill")
        values = []
        for record in records:
            if record.operation_id not in {
                "list_goods_bid_awards",
                "list_construction_bid_awards",
                "list_service_bid_awards",
                "list_foreign_bid_awards",
            }:
                continue
            key = tuple(
                str(record.payload.get(name) or "").strip()
                for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
            )
            if key[0]:
                values.append(
                    (*key, record.source_record_hash, queue_class, record.window.end)
                )
        if not values:
            return 0
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO ingestion.bid_opening_enrichment_queue "
                    "(notice_number,notice_order,bid_classification_number,rebid_number,"
                    "award_source_record_hash,queue_class,priority_date) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
                    "(notice_number,notice_order,bid_classification_number,rebid_number) "
                    "DO UPDATE SET award_source_record_hash=EXCLUDED.award_source_record_hash,"
                    "status=CASE WHEN ingestion.bid_opening_enrichment_queue."
                    "award_source_record_hash<>EXCLUDED.award_source_record_hash "
                    "THEN 'pending' ELSE ingestion.bid_opening_enrichment_queue.status END,"
                    "next_retry_at=CASE WHEN ingestion.bid_opening_enrichment_queue."
                    "award_source_record_hash<>EXCLUDED.award_source_record_hash "
                    "THEN now() ELSE ingestion.bid_opening_enrichment_queue.next_retry_at END,"
                    "queue_class=CASE WHEN EXCLUDED.queue_class='incremental' THEN 'incremental' "
                    "ELSE ingestion.bid_opening_enrichment_queue.queue_class END,"
                    "priority_date=GREATEST(ingestion.bid_opening_enrichment_queue.priority_date,"
                    "EXCLUDED.priority_date),"
                    "updated_at=now()",
                    values,
                )
        return len(values)

    async def claim_bid_opening_enrichment(
        self, execution_id: UUID, queue_mode: str, limit: int, lease_minutes: int = 15
    ) -> list[RawProviderRecord]:
        if queue_mode not in {"incremental", "backfill", "retry"}:
            raise ValueError("queue_mode must be incremental, backfill, or retry")
        now = datetime.now(timezone.utc)
        if queue_mode == "retry":
            eligibility = "q.status='retry_wait' AND q.next_retry_at<=now()"
            ordering = "q.next_retry_at,q.priority_date DESC NULLS LAST,q.updated_at"
        else:
            eligibility = (
                "q.status='pending' AND q.queue_class=%s AND q.next_retry_at<=now()"
            )
            ordering = "q.priority_date DESC NULLS LAST,q.updated_at"
        eligibility = (
            f"(({eligibility}) OR (q.status='processing' AND q.lease_until<now() "
            + ("AND q.queue_class=%s" if queue_mode != "retry" else "")
            + "))"
        )
        parameters: list[Any] = (
            [] if queue_mode == "retry" else [queue_mode, queue_mode]
        )
        parameters.extend([limit, lease_minutes])
        async with connect(self.database_url) as connection:
            rows = await (
                await connection.execute(
                    "WITH candidates AS (SELECT q.notice_number,q.notice_order,"
                    "q.bid_classification_number,q.rebid_number FROM "
                    "ingestion.bid_opening_enrichment_queue q WHERE "
                    f"{eligibility} ORDER BY {ordering} "
                    "FOR UPDATE OF q SKIP LOCKED LIMIT %s), "
                    "claimed AS (UPDATE ingestion.bid_opening_enrichment_queue q SET "
                    "status='processing',lease_until=now()+(%s||' minutes')::interval,updated_at=now() "
                    "FROM candidates c WHERE (q.notice_number,q.notice_order,q.bid_classification_number,"
                    "q.rebid_number)=(c.notice_number,c.notice_order,c.bid_classification_number,"
                    "c.rebid_number) RETURNING q.*) SELECT a.*,c.award_source_record_hash "
                    "FROM claimed c JOIN public_procurement.bid_awards a USING "
                    "(notice_number,notice_order,bid_classification_number,rebid_number)",
                    parameters,
                )
            ).fetchall()
            columns = [
                description.name
                for description in (
                    await connection.execute(
                        "SELECT a.*,q.award_source_record_hash FROM public_procurement.bid_awards a "
                        "JOIN ingestion.bid_opening_enrichment_queue q USING "
                        "(notice_number,notice_order,bid_classification_number,rebid_number) LIMIT 0"
                    )
                ).description
            ]
        operation_by_work_type = {
            "goods": "list_goods_bid_awards",
            "construction": "list_construction_bid_awards",
            "service": "list_service_bid_awards",
            "foreign": "list_foreign_bid_awards",
        }
        records = []
        for values in rows:
            row = dict(zip(columns, values, strict=True))
            observed = row.get("final_award_date") or now.date()
            payload = {
                "bidNtceNo": row["notice_number"],
                "bidNtceOrd": row["notice_order"],
                "bidClsfcNo": row["bid_classification_number"],
                "rbidNo": row["rebid_number"],
                "bidwinnrBizno": row.get("winner_business_registration_number"),
            }
            records.append(
                RawProviderRecord(
                    raw_record_id=uuid4(),
                    execution_id=execution_id,
                    connector_id="pps_bid_result_api",
                    operation_id=operation_by_work_type[row["work_type"]],
                    window=CollectionWindow(observed, observed),
                    fetched_at=now,
                    source_record_hash=row["award_source_record_hash"],
                    payload=payload,
                )
            )
        return records

    async def finish_bid_opening_enrichment(
        self,
        successful: Iterable[RawProviderRecord],
        failed: Iterable[RawProviderRecord],
    ) -> None:
        def keys(
            records: Iterable[RawProviderRecord],
        ) -> list[tuple[str, str, str, str]]:
            return [
                tuple(
                    str(record.payload.get(name) or "").strip()
                    for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
                )
                for record in records
            ]

        successful_keys, failed_keys = keys(successful), keys(failed)
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                if successful_keys:
                    await cursor.executemany(
                        "UPDATE ingestion.bid_opening_enrichment_queue q SET "
                        "status=CASE WHEN verified.complete THEN 'completed' "
                        "WHEN q.attempts+1>=3 THEN 'partial_completed' ELSE 'retry_wait' END,"
                        "attempts=CASE WHEN verified.complete THEN q.attempts ELSE q.attempts+1 END,"
                        "completed_at=CASE WHEN verified.complete THEN now() ELSE NULL END,"
                        "next_retry_at=CASE WHEN verified.complete THEN q.next_retry_at "
                        "WHEN q.attempts+1>=3 THEN 'infinity'::timestamptz "
                        "WHEN q.attempts<1 THEN now()+interval '30 minutes' "
                        "WHEN q.attempts<2 THEN now()+interval '2 hours' "
                        "WHEN q.attempts<3 THEN now()+interval '12 hours' "
                        "ELSE now()+interval '1 day' END,"
                        "lease_until=NULL,last_error_code=CASE WHEN verified.complete THEN NULL "
                        "ELSE 'opening_response_incomplete' END,updated_at=now() FROM ("
                        "SELECT c.notice_number,c.notice_order,c.bid_classification_number,c.rebid_number,"
                        "c.award_source_record_hash, c.selected_business_numbers IS NOT NULL AND "
                        "c.selected_business_numbers=ARRAY(SELECT DISTINCT p.business_registration_number "
                        "FROM public_procurement.bid_opening_participants p WHERE "
                        "(p.notice_number,p.notice_order,p.bid_classification_number,p.rebid_number)="
                        "(c.notice_number,c.notice_order,c.bid_classification_number,c.rebid_number) "
                        "ORDER BY p.business_registration_number) AS complete "
                        "FROM ingestion.bid_opening_collection_status c) verified WHERE "
                        "(verified.notice_number,verified.notice_order,verified.bid_classification_number,"
                        "verified.rebid_number)=(q.notice_number,q.notice_order,"
                        "q.bid_classification_number,q.rebid_number) AND "
                        "verified.award_source_record_hash=q.award_source_record_hash AND "
                        "q.notice_number=%s AND q.notice_order=%s AND q.bid_classification_number=%s "
                        "AND q.rebid_number=%s",
                        successful_keys,
                    )
                if failed_keys:
                    await cursor.executemany(
                        "UPDATE ingestion.bid_opening_enrichment_queue SET status=CASE "
                        "WHEN attempts+1>=5 THEN 'permanent_failure' ELSE 'retry_wait' END,"
                        "attempts=attempts+1,lease_until=NULL,last_error_code='opening_lookup_failed',"
                        "next_retry_at=CASE WHEN attempts+1>=5 THEN 'infinity'::timestamptz "
                        "ELSE now()+CASE WHEN attempts<1 THEN interval '30 minutes' "
                        "WHEN attempts<2 THEN interval '2 hours' WHEN attempts<3 THEN interval '12 hours' "
                        "ELSE interval '1 day' END END,updated_at=now() "
                        "WHERE notice_number=%s "
                        "AND notice_order=%s AND bid_classification_number=%s AND rebid_number=%s",
                        failed_keys,
                    )

    async def mark_bid_openings_checked(
        self,
        awards: Iterable[RawProviderRecord],
        participants: Iterable[RawProviderRecord],
        execution_id: UUID,
    ) -> int:
        awards = list(awards)
        participants = list(participants)
        selected_numbers: dict[tuple[str, str, str, str], set[str]] = {}
        if awards:
            first = awards[0]
            selected = select_participants(
                ExtractedBatch(execution_id, first.window, awards),
                ExtractedBatch(execution_id, first.window, participants),
            )
            for record in selected.records:
                key = tuple(
                    str(record.payload.get(name) or "").strip()
                    for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
                )
                number = "".join(
                    c
                    for c in str(record.payload.get("prcbdrBizno") or "")
                    if c.isdigit()
                )
                if number:
                    selected_numbers.setdefault(key, set()).add(number)
        counts: dict[tuple[str, str, str, str], int] = {}
        for record in participants:
            key = tuple(
                str(record.payload.get(name) or "").strip()
                for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
            )
            counts[key] = counts.get(key, 0) + 1
        values = []
        for record in awards:
            key = tuple(
                str(record.payload.get(name) or "").strip()
                for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
            )
            values.append(
                (
                    *key,
                    record.source_record_hash,
                    counts.get(key, 0),
                    execution_id,
                    sorted(selected_numbers.get(key, set())),
                )
            )
        if not values:
            return 0
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO ingestion.bid_opening_collection_status "
                    "(notice_number,notice_order,bid_classification_number,rebid_number,"
                    "award_source_record_hash,participant_count,execution_id,selected_business_numbers) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
                    "(notice_number,notice_order,bid_classification_number,rebid_number) "
                    "DO UPDATE SET award_source_record_hash=EXCLUDED.award_source_record_hash,"
                    "participant_count=EXCLUDED.participant_count,execution_id=EXCLUDED.execution_id,"
                    "selected_business_numbers=EXCLUDED.selected_business_numbers,checked_at=now()",
                    values,
                )
        return len(values)

    async def replace_bid_opening_participants(
        self, awards: Iterable[RawProviderRecord], batch: NormalizedBidResultBatch
    ) -> LoadSummary:
        keys = [
            tuple(
                str(record.payload.get(name) or "").strip()
                for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
            )
            for record in awards
        ]
        async with connect(self.database_url) as connection:
            if keys:
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        "DELETE FROM public_procurement.bid_opening_participants "
                        "WHERE notice_number=%s AND notice_order=%s "
                        "AND bid_classification_number=%s AND rebid_number=%s",
                        keys,
                    )
            await self._upsert_many(
                connection,
                "public_procurement.bid_opening_participants",
                batch.opening_participants,
                (
                    "notice_number",
                    "notice_order",
                    "bid_classification_number",
                    "rebid_number",
                    "business_registration_number",
                ),
            )
        return LoadSummary(opening_participants=len(batch.opening_participants))
