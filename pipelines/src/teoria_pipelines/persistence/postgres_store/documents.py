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


class DocumentStoreMixin:
    """documents persistence operations."""

    def upsert_bid_notices(self, batch: NormalizedBidNoticeBatch) -> tuple[LoadSummary, list[BidNoticeKey]]:
        changed: list[BidNoticeKey] = []
        with psycopg.connect(self.database_url) as connection:
            for row in batch.notices:
                values = dict(row)
                values["source_payload"] = Jsonb(values["source_payload"])
                columns = tuple(values)
                assignments = [column for column in columns if column not in {"notice_number", "notice_order"}]
                result = connection.execute(
                    f"INSERT INTO public_procurement.bid_notices ({', '.join(columns)}) "
                    f"VALUES ({', '.join('%(' + column + ')s' for column in columns)}) "
                    "ON CONFLICT (notice_number, notice_order) DO UPDATE SET "
                    + ", ".join(f"{column}=EXCLUDED.{column}" for column in assignments)
                    + ", updated_at=now() "
                    "WHERE public_procurement.bid_notices.source_record_hash "
                    "IS DISTINCT FROM EXCLUDED.source_record_hash "
                    "OR public_procurement.bid_notices.enrichment_checked_at IS NULL "
                    "RETURNING notice_number, notice_order",
                    values,
                ).fetchone()
                if result:
                    changed.append(BidNoticeKey(result[0], result[1]))
            self._upsert_many(
                connection, "public_procurement.bid_notice_documents", batch.documents,
                ("document_id",),
            )
        return LoadSummary(notices=len(batch.notices), documents=len(batch.documents)), changed

    def upsert_bid_notice_enrichment(self, batch: NormalizedBidNoticeBatch,
                                     notices: list[BidNoticeKey]) -> LoadSummary:
        with psycopg.connect(self.database_url) as connection:
            self._upsert_many(
                connection, "public_procurement.bid_notice_license_restrictions",
                batch.license_restrictions,
                ("notice_number", "notice_order", "restriction_group_number", "restriction_sequence"),
            )
            self._upsert_many(
                connection, "public_procurement.bid_notice_participation_regions",
                batch.participation_regions,
                ("notice_number", "notice_order", "restriction_sequence"),
            )
            if notices:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        "UPDATE public_procurement.bid_notices "
                        "SET enrichment_checked_at=now(), updated_at=now() "
                        "WHERE notice_number=%s AND notice_order=%s",
                        [(item.notice_number, item.notice_order) for item in notices],
                    )
        return LoadSummary(
            license_restrictions=len(batch.license_restrictions),
            participation_regions=len(batch.participation_regions),
        )

    def claim_pending_documents(self, limit: int, max_attempts: int = 3) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "WITH candidates AS ("
                " SELECT document_id FROM public_procurement.bid_notice_documents"
                " WHERE status IN ('pending', 'failed') AND attempts < %s AND next_retry_at <= now()"
                " ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s"
                ") UPDATE public_procurement.bid_notice_documents d"
                " SET status='processing', attempts=d.attempts+1, updated_at=now()"
                " FROM candidates c WHERE d.document_id=c.document_id"
                " RETURNING d.document_id, d.notice_number, d.notice_order, d.file_name, d.source_url",
                (max_attempts, limit),
            ).fetchall()
        return [
            {"document_id": row[0], "notice_number": row[1], "notice_order": row[2],
             "file_name": row[3], "source_url": row[4]}
            for row in rows
        ]

    def complete_document(self, document_id: UUID, *, media_type: str | None,
                          file_size: int, checksum: str, object_key: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET status='stored',"
                " media_type=%s, file_size=%s, checksum=%s, object_key=%s,"
                " downloaded_at=now(), last_error_code=NULL, updated_at=now()"
                " WHERE document_id=%s",
                (media_type, file_size, checksum, object_key, document_id),
            )

    def fail_document(self, document_id: UUID, error_code: str, *, unsupported: bool = False) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET status=%s,"
                " last_error_code=%s, next_retry_at=now() + interval '1 hour', updated_at=now()"
                " WHERE document_id=%s",
                ("unsupported" if unsupported else "failed", error_code, document_id),
            )

    def claim_expired_document_objects(self, retention_days: int,
                                       limit: int) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "WITH candidates AS ("
                " SELECT d.document_id FROM public_procurement.bid_notice_documents d"
                " JOIN public_procurement.bid_notices n USING (notice_number, notice_order)"
                " WHERE n.bid_deadline_at IS NOT NULL"
                " AND n.bid_deadline_at < now() - (%s * interval '1 day')"
                " AND d.storage_status IN ('active','purge_failed')"
                " AND (d.object_key IS NOT NULL OR d.parsed_object_key IS NOT NULL)"
                " AND d.status <> 'processing' AND d.parse_status <> 'processing'"
                " AND NOT EXISTS (SELECT 1 FROM public_procurement.bid_eligibility_extractions e"
                "   WHERE e.notice_number=d.notice_number AND e.notice_order=d.notice_order"
                "   AND e.status='processing')"
                " ORDER BY n.bid_deadline_at, d.created_at"
                " FOR UPDATE OF d SKIP LOCKED LIMIT %s"
                ") UPDATE public_procurement.bid_notice_documents d"
                " SET storage_status='purging', purge_attempts=d.purge_attempts+1,"
                " purge_error_code=NULL, updated_at=now() FROM candidates c"
                " WHERE d.document_id=c.document_id"
                " RETURNING d.document_id,d.notice_number,d.notice_order,"
                " d.object_key,d.parsed_object_key",
                (retention_days, limit),
            ).fetchall()
        keys = ("document_id", "notice_number", "notice_order", "object_key", "parsed_object_key")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def complete_document_purge(self, document_id: UUID) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET object_key=NULL,"
                " parsed_object_key=NULL,storage_status='purged',purged_at=now(),"
                " purge_reason='retention_expired',purge_error_code=NULL,updated_at=now()"
                " WHERE document_id=%s",
                (document_id,),
            )

    def fail_document_purge(self, document_id: UUID, error_code: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET storage_status='purge_failed',"
                " purge_error_code=%s,updated_at=now() WHERE document_id=%s",
                (error_code, document_id),
            )

    def list_expired_extraction_objects(self, retention_days: int,
                                        limit: int) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT e.extraction_id,e.raw_output_object_key FROM "
                "public_procurement.bid_eligibility_extractions e JOIN "
                "public_procurement.bid_notices n USING (notice_number,notice_order) "
                "WHERE n.bid_deadline_at IS NOT NULL "
                "AND n.bid_deadline_at < now()-(%s * interval '1 day') "
                "AND e.status='completed' AND e.raw_output_object_key IS NOT NULL "
                "ORDER BY n.bid_deadline_at,e.finished_at LIMIT %s",
                (retention_days, limit),
            ).fetchall()
        return [{"extraction_id": row[0], "object_key": row[1]} for row in rows]

    def complete_extraction_object_purge(self, extraction_id: UUID) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_eligibility_extractions SET "
                "raw_output_object_key=NULL,raw_output_purged_at=now() WHERE extraction_id=%s",
                (extraction_id,),
            )

    def record_document_purge_run(self, *, purge_run_id: UUID, retention_days: int,
                                  target_count: int, purged_count: int,
                                  deleted_object_count: int, failed_count: int,
                                  started_at: datetime) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO public_procurement.bid_document_purge_runs "
                "(purge_run_id,retention_days,target_count,purged_document_count,"
                "deleted_object_count,failed_document_count,started_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (purge_run_id, retention_days, target_count, purged_count,
                 deleted_object_count, failed_count, started_at),
            )

    def claim_documents_for_parsing(self, limit: int, parser_version: str,
                                    max_attempts: int = 3) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "WITH candidates AS (SELECT document_id, "
                "parser_version IS DISTINCT FROM %s AS parser_version_changed "
                "FROM public_procurement.bid_notice_documents "
                "WHERE status='stored' AND (((parse_status IN ('pending','failed') "
                "OR (parse_status='processing' AND updated_at <= now()-interval '1 hour')) "
                "AND parse_attempts < %s) "
                "OR (parse_status IN ('parsed','unsupported') "
                "AND parser_version IS DISTINCT FROM %s)) "
                "AND parse_next_retry_at <= now() ORDER BY downloaded_at "
                "FOR UPDATE SKIP LOCKED LIMIT %s) "
                "UPDATE public_procurement.bid_notice_documents d SET parse_status='processing', "
                "parse_attempts=CASE WHEN c.parser_version_changed THEN 1 "
                "ELSE d.parse_attempts+1 END, updated_at=now() FROM candidates c "
                "WHERE d.document_id=c.document_id RETURNING d.document_id, d.notice_number, "
                "d.notice_order, d.file_name, d.media_type, d.checksum, d.object_key",
                (parser_version, max_attempts, parser_version, limit),
            ).fetchall()
        keys = ("document_id", "notice_number", "notice_order", "file_name", "media_type", "checksum", "object_key")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def complete_document_parse(self, document_id: UUID, *, parser_name: str,
                                parser_version: str, parsed_object_key: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET parse_status='parsed', "
                "parser_name=%s, parser_version=%s, parsed_object_key=%s, parsed_at=now(), "
                "parse_error_code=NULL, updated_at=now() WHERE document_id=%s",
                (parser_name, parser_version, parsed_object_key, document_id),
            )

    def fail_document_parse(self, document_id: UUID, error_code: str,
                            *, parser_version: str | None = None,
                            unsupported: bool = False) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE public_procurement.bid_notice_documents SET parse_status=%s, "
                "parse_error_code=%s, parser_version=%s, "
                "parse_next_retry_at=now()+interval '1 hour', updated_at=now() "
                "WHERE document_id=%s",
                ("unsupported" if unsupported else "failed", error_code, parser_version, document_id),
            )

