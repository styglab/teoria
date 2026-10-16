from __future__ import annotations

from typing import Any
from uuid import UUID

from teoria_pipelines.persistence.connection import connect
from psycopg.types.json import Jsonb

from teoria_pipelines.domains.public_procurement.bid_notices.models import (
    BidNoticeKey,
    NormalizedBidNoticeBatch,
)
from teoria_pipelines.domains.public_procurement.models import LoadSummary
from teoria_pipelines.domains.public_procurement.repository import (
    ProcurementRunRepository,
)
from teoria_pipelines.models import ExtractedBatch


class BidNoticeRepository(ProcurementRunRepository):
    """Persist notices and the API-provided license and region restrictions."""

    async def upsert_bid_notices(
        self, batch: NormalizedBidNoticeBatch
    ) -> tuple[LoadSummary, list[BidNoticeKey]]:
        changed: list[BidNoticeKey] = []
        async with connect(self.database_url) as connection:
            for row in batch.notices:
                values = dict(row)
                values["source_payload"] = Jsonb(values["source_payload"])
                if values.get("purchase_items") is not None:
                    values["purchase_items"] = Jsonb(values["purchase_items"])
                columns = tuple(values)
                assignments = [
                    column
                    for column in columns
                    if column not in {"notice_number", "notice_order"}
                ]
                result = await (
                    await connection.execute(
                        f"INSERT INTO public_procurement.bid_notices ({', '.join(columns)}) "
                        f"VALUES ({', '.join('%(' + column + ')s' for column in columns)}) "
                        "ON CONFLICT (notice_number, notice_order) DO UPDATE SET "
                        + ", ".join(
                            f"{column}=EXCLUDED.{column}" for column in assignments
                        )
                        + ", enrichment_checked_at=CASE WHEN "
                        "public_procurement.bid_notices.source_record_hash "
                        "IS DISTINCT FROM EXCLUDED.source_record_hash THEN NULL "
                        "ELSE public_procurement.bid_notices.enrichment_checked_at END, "
                        "enrichment_claimed_at=CASE WHEN "
                        "public_procurement.bid_notices.source_record_hash "
                        "IS DISTINCT FROM EXCLUDED.source_record_hash THEN NULL "
                        "ELSE public_procurement.bid_notices.enrichment_claimed_at END, "
                        "updated_at=now() "
                        "WHERE public_procurement.bid_notices.source_record_hash "
                        "IS DISTINCT FROM EXCLUDED.source_record_hash "
                        "OR public_procurement.bid_notices.enrichment_checked_at IS NULL "
                        "RETURNING notice_number, notice_order",
                        values,
                    )
                ).fetchone()
                if result:
                    changed.append(BidNoticeKey(result[0], result[1]))
        return LoadSummary(notices=len(batch.notices)), changed

    async def claim_pending_bid_notice_enrichment(
        self,
        limit: int,
        minimum_age_days: int = 7,
        lease_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        async with connect(self.database_url) as connection:
            rows = await (
                await connection.execute(
                    "WITH candidates AS ("
                    " SELECT notice_number,notice_order"
                    " FROM public_procurement.bid_notices"
                    " WHERE enrichment_checked_at IS NULL"
                    " AND notice_published_at < now()-(%s * interval '1 day')"
                    " AND (enrichment_claimed_at IS NULL OR enrichment_claimed_at"
                    " < now()-(%s * interval '1 minute'))"
                    " ORDER BY notice_published_at DESC,notice_number,notice_order"
                    " FOR UPDATE SKIP LOCKED LIMIT %s"
                    ") UPDATE public_procurement.bid_notices n"
                    " SET enrichment_claimed_at=now(),updated_at=now()"
                    " FROM candidates c WHERE n.notice_number=c.notice_number"
                    " AND n.notice_order=c.notice_order"
                    " RETURNING n.notice_number,n.notice_order,(n.notice_published_at AT TIME ZONE 'Asia/Seoul')::date",
                    (minimum_age_days, lease_minutes, limit),
                )
            ).fetchall()
        return [
            {"notice_number": row[0], "notice_order": row[1], "published_date": row[2]}
            for row in rows
        ]

    async def upsert_bid_notice_enrichment(
        self, batch: NormalizedBidNoticeBatch, notices: list[BidNoticeKey]
    ) -> LoadSummary:
        async with connect(self.database_url) as connection:
            await self._upsert_many(
                connection,
                "public_procurement.bid_notice_license_restrictions",
                batch.license_restrictions,
                (
                    "notice_number",
                    "notice_order",
                    "restriction_group_number",
                    "restriction_sequence",
                ),
            )
            await self._upsert_many(
                connection,
                "public_procurement.bid_notice_participation_regions",
                batch.participation_regions,
                ("notice_number", "notice_order", "restriction_sequence"),
            )
            if notices:
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        "UPDATE public_procurement.bid_notices "
                        "SET enrichment_checked_at=now(), enrichment_claimed_at=NULL, "
                        "updated_at=now() "
                        "WHERE notice_number=%s AND notice_order=%s",
                        [(item.notice_number, item.notice_order) for item in notices],
                    )
        return LoadSummary(
            license_restrictions=len(batch.license_restrictions),
            participation_regions=len(batch.participation_regions),
        )

    async def begin_bid_notice_requirement_collection(
        self,
        notices: list[BidNoticeKey],
        execution_id: UUID,
    ) -> None:
        values = [
            (item.notice_number, item.notice_order, category, execution_id)
            for item in notices
            for category in ("industry_license", "region")
        ]
        if not values:
            return
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO ingestion.bid_notice_requirement_collection_status "
                    "(notice_number,notice_order,category,status,record_count,execution_id,"
                    "error_code,checked_at) VALUES (%s,%s,%s,'pending',NULL,%s,NULL,NULL) "
                    "ON CONFLICT (notice_number,notice_order,category) DO UPDATE SET "
                    "status='pending',record_count=NULL,execution_id=EXCLUDED.execution_id,"
                    "error_code=NULL,checked_at=NULL,updated_at=now()",
                    values,
                )

    async def complete_bid_notice_requirement_collection(
        self,
        notices: list[BidNoticeKey],
        batch: ExtractedBatch,
        execution_id: UUID,
    ) -> None:
        operation_categories = {
            "list_license_restrictions": "industry_license",
            "list_participation_regions": "region",
        }
        counts = {
            (item.notice_number, item.notice_order, category): 0
            for item in notices
            for category in operation_categories.values()
        }
        for record in batch.records:
            category = operation_categories.get(record.operation_id)
            if category is None:
                continue
            key = (
                str(record.payload.get("bidNtceNo") or "").strip(),
                str(record.payload.get("bidNtceOrd") or "").strip(),
                category,
            )
            if key in counts:
                counts[key] += 1
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "UPDATE ingestion.bid_notice_requirement_collection_status SET "
                    "status='completed',record_count=%s,execution_id=%s,error_code=NULL,"
                    "checked_at=now(),updated_at=now() WHERE notice_number=%s "
                    "AND notice_order=%s AND category=%s",
                    [
                        (count, execution_id, number, order, category)
                        for (number, order, category), count in counts.items()
                    ],
                )

    async def fail_bid_notice_requirement_collection(
        self,
        notices: list[BidNoticeKey],
        execution_id: UUID,
        error_code: str,
    ) -> None:
        values = [
            (execution_id, error_code, item.notice_number, item.notice_order, category)
            for item in notices
            for category in ("industry_license", "region")
        ]
        if not values:
            return
        async with connect(self.database_url) as connection:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "UPDATE ingestion.bid_notice_requirement_collection_status SET "
                    "status='failed',record_count=NULL,execution_id=%s,error_code=%s,"
                    "checked_at=now(),updated_at=now() WHERE notice_number=%s "
                    "AND notice_order=%s AND category=%s",
                    values,
                )
