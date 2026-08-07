from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID
from uuid import uuid4, uuid5, NAMESPACE_URL

import psycopg
from psycopg.types.json import Jsonb

from teoria_pipelines.models import (
    BidNoticeKey,
    CollectionWindow,
    LoadSummary,
    NormalizedBatch,
    NormalizedBidNoticeBatch,
    RawProviderRecord,
)


class PostgresStore:
    """Data DB writer. A new short-lived connection is used per task boundary."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("TEORIA_PIPELINE_DATA_DATABASE_URL is required")
        self.database_url = database_url

    def apply_migrations(self, migration_root: Path) -> list[str]:
        applied: list[str] = []
        with psycopg.connect(self.database_url) as connection:
            connection.execute("CREATE SCHEMA IF NOT EXISTS ingestion")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS ingestion.schema_migrations "
                "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            existing = {
                row[0]
                for row in connection.execute("SELECT version FROM ingestion.schema_migrations")
            }
            for path in sorted(migration_root.glob("*.sql")):
                if path.name in existing:
                    continue
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO ingestion.schema_migrations (version) VALUES (%s)",
                    (path.name,),
                )
                applied.append(path.name)
        return applied

    def start_run(self, execution_id: UUID, pipeline_id: str, window: CollectionWindow,
                  started_at: datetime | None = None) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_runs "
                "(execution_id, pipeline_id, window_start, window_end, started_at, status) "
                "VALUES (%s, %s, %s, %s, %s, 'running')",
                (execution_id, pipeline_id, window.start, window.end,
                 started_at or datetime.now(timezone.utc)),
            )

    def complete_run(self, execution_id: UUID, summary: LoadSummary) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='completed', finished_at=now(), "
                "raw_record_count=%s, contract_count=%s, notice_count=%s, document_count=%s "
                "WHERE execution_id=%s",
                (summary.raw_records, summary.contracts, summary.notices,
                 summary.documents, execution_id),
            )

    def fail_run(self, execution_id: UUID, error_code: str) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "UPDATE ingestion.pipeline_runs SET status='failed', finished_at=now(), error_code=%s "
                "WHERE execution_id=%s",
                (error_code, execution_id),
            )

    def save_raw_records(self, records: Iterable[RawProviderRecord]) -> int:
        values = list(records)
        if not values:
            return 0
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO ingestion.raw_provider_records "
                    "(raw_record_id, execution_id, connector_id, operation_id, window_start, window_end, "
                    "fetched_at, source_record_hash, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (execution_id, connector_id, operation_id, source_record_hash) DO NOTHING",
                    [
                        (record.raw_record_id, record.execution_id, record.connector_id,
                         record.operation_id, record.window.start, record.window.end,
                         record.fetched_at, record.source_record_hash, Jsonb(record.payload))
                        for record in values
                    ],
                )
                inserted = cursor.rowcount
        return inserted

    def upsert_normalized(self, batch: NormalizedBatch) -> LoadSummary:
        with psycopg.connect(self.database_url) as connection:
            self._upsert_many(connection, "public_procurement.contracts", batch.contracts,
                              ("unified_contract_number",))
            self._upsert_many(connection, "public_procurement.public_organizations",
                              batch.organizations, ("organization_code",))
            self._upsert_many(connection, "public_procurement.contract_suppliers",
                              batch.suppliers, ("unified_contract_number", "supplier_sequence"))
            self._upsert_many(connection, "public_procurement.contract_demand_organizations",
                              batch.demand_organizations,
                              ("unified_contract_number", "demand_organization_sequence"))
        return LoadSummary(
            contracts=len(batch.contracts),
            suppliers=len(batch.suppliers),
            organizations=len(batch.organizations),
            demand_organizations=len(batch.demand_organizations),
        )

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
                "WITH candidates AS (SELECT document_id FROM public_procurement.bid_notice_documents "
                "WHERE status='stored' AND ((parse_status IN ('pending','failed') "
                "AND parse_attempts < %s) "
                "OR (parse_status='unsupported' AND parser_version IS DISTINCT FROM %s)) "
                "AND parse_next_retry_at <= now() ORDER BY downloaded_at "
                "FOR UPDATE SKIP LOCKED LIMIT %s) "
                "UPDATE public_procurement.bid_notice_documents d SET parse_status='processing', "
                "parse_attempts=parse_attempts+1, updated_at=now() FROM candidates c "
                "WHERE d.document_id=c.document_id RETURNING d.document_id, d.notice_number, "
                "d.notice_order, d.file_name, d.media_type, d.checksum, d.object_key",
                (max_attempts, parser_version, limit),
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

    def list_notices_for_eligibility_extraction(self, limit: int,
                                                download_max_attempts: int = 3,
                                                parse_max_attempts: int = 3) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as connection:
            notices = connection.execute(
                "SELECT n.notice_number, n.notice_order, n.source_record_hash, n.bid_deadline_at "
                "FROM public_procurement.bid_notices n WHERE (EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_documents d WHERE d.notice_number=n.notice_number "
                "AND d.notice_order=n.notice_order AND d.parse_status='parsed' "
                "AND d.storage_status='active' AND d.parsed_object_key IS NOT NULL) OR EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_license_restrictions l WHERE l.notice_number=n.notice_number "
                "AND l.notice_order=n.notice_order) OR EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_participation_regions r WHERE r.notice_number=n.notice_number "
                "AND r.notice_order=n.notice_order)) AND NOT EXISTS (SELECT 1 FROM "
                "public_procurement.bid_notice_documents d WHERE d.notice_number=n.notice_number "
                "AND d.notice_order=n.notice_order AND (d.status IN ('pending','processing') "
                "OR (d.status='failed' AND d.attempts < %s) "
                "OR (d.status='stored' AND (d.parse_status IN ('pending','processing') "
                "OR (d.parse_status='failed' AND d.parse_attempts < %s))))) "
                "ORDER BY n.notice_published_at DESC LIMIT %s", (download_max_attempts, parse_max_attempts, limit)
            ).fetchall()
            result = []
            for number, order, notice_hash, deadline in notices:
                documents = connection.execute(
                    "SELECT document_id, file_name, checksum, parsed_object_key FROM "
                    "public_procurement.bid_notice_documents WHERE notice_number=%s AND notice_order=%s "
                    "AND parse_status='parsed' AND storage_status='active' "
                    "AND parsed_object_key IS NOT NULL ORDER BY document_slot", (number, order)
                ).fetchall()
                unavailable_documents = connection.execute(
                    "SELECT document_id, file_name, status, attempts, last_error_code, "
                    "parse_status, parse_attempts, parse_error_code FROM "
                    "public_procurement.bid_notice_documents WHERE notice_number=%s "
                    "AND notice_order=%s AND NOT (status='stored' AND parse_status='parsed') "
                    "ORDER BY document_slot", (number, order)
                ).fetchall()
                licenses = connection.execute(
                    "SELECT restriction_group_number, restriction_sequence, license_restriction_name, "
                    "permitted_industry_list, industry_main_field_list, business_type_name, source_record_hash "
                    "FROM public_procurement.bid_notice_license_restrictions "
                    "WHERE notice_number=%s AND notice_order=%s", (number, order)
                ).fetchall()
                regions = connection.execute(
                    "SELECT restriction_sequence, participation_region_name, business_type_name, source_record_hash "
                    "FROM public_procurement.bid_notice_participation_regions "
                    "WHERE notice_number=%s AND notice_order=%s", (number, order)
                ).fetchall()
                total_documents = len(documents) + len(unavailable_documents)
                unavailable_count = len(unavailable_documents)
                completeness = (
                    "api_only" if total_documents == 0
                    else "partial" if unavailable_count else "complete"
                )
                result.append({
                    "notice_number": number, "notice_order": order,
                    "notice_hash": notice_hash, "bid_deadline_at": deadline.isoformat() if deadline else None,
                    "documents": [dict(zip(("document_id", "file_name", "checksum", "parsed_object_key"), row, strict=True)) for row in documents],
                    "unavailable_documents": [dict(zip(("document_id", "file_name", "status", "attempts", "error_code", "parse_status", "parse_attempts", "parse_error_code"), row, strict=True)) for row in unavailable_documents],
                    "licenses": [dict(zip(("group", "sequence", "name", "permitted_industries", "main_fields", "business_type", "source_hash"), row, strict=True)) for row in licenses],
                    "regions": [dict(zip(("sequence", "name", "business_type", "source_hash"), row, strict=True)) for row in regions],
                    "coverage": {
                        "completeness": completeness,
                        "requires_review": unavailable_count > 0,
                        "total_document_count": total_documents,
                        "parsed_document_count": len(documents),
                        "unavailable_document_count": unavailable_count,
                        "structured_requirement_count": len(licenses) + len(regions),
                    },
                })
        return result

    def completed_eligibility_fingerprints(self) -> set[str]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT input_fingerprint FROM public_procurement.bid_eligibility_extractions "
                "WHERE status='completed'"
            ).fetchall()
        return {row[0] for row in rows}

    def save_eligibility_extraction(self, notice: dict[str, Any], fingerprint: str,
                                    result: dict[str, Any], raw_output_object_key: str,
                                    model_name: str | None) -> bool:
        extraction_id = uuid4()
        with psycopg.connect(self.database_url) as connection:
            existing = connection.execute(
                "SELECT 1 FROM public_procurement.bid_eligibility_extractions WHERE "
                "notice_number=%s AND notice_order=%s AND input_fingerprint=%s AND status='completed'",
                (notice["notice_number"], notice["notice_order"], fingerprint),
            ).fetchone()
            if existing:
                return False
            connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_extractions "
                "(extraction_id,notice_number,notice_order,input_fingerprint,schema_version,skill_version,model_name,status,raw_output_object_key,finished_at,completeness,requires_review,total_document_count,parsed_document_count,unavailable_document_count,unavailable_documents,structured_requirement_count) "
                "VALUES (%s,%s,%s,%s,%s,'1.0.0',%s,'completed',%s,now(),%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (notice_number,notice_order,input_fingerprint) DO UPDATE SET "
                "extraction_id=EXCLUDED.extraction_id,status='completed',model_name=EXCLUDED.model_name,"
                "raw_output_object_key=EXCLUDED.raw_output_object_key,error_code=NULL,finished_at=now(),"
                "completeness=EXCLUDED.completeness,requires_review=EXCLUDED.requires_review,"
                "total_document_count=EXCLUDED.total_document_count,parsed_document_count=EXCLUDED.parsed_document_count,"
                "unavailable_document_count=EXCLUDED.unavailable_document_count,unavailable_documents=EXCLUDED.unavailable_documents,"
                "structured_requirement_count=EXCLUDED.structured_requirement_count",
                (extraction_id, notice["notice_number"], notice["notice_order"], fingerprint,
                 result["schema_version"], model_name, raw_output_object_key,
                 notice["coverage"]["completeness"], notice["coverage"]["requires_review"],
                 notice["coverage"]["total_document_count"], notice["coverage"]["parsed_document_count"],
                 notice["coverage"]["unavailable_document_count"], Jsonb([
                     {**item, "document_id": str(item["document_id"])}
                     for item in notice["unavailable_documents"]
                 ]),
                 notice["coverage"]["structured_requirement_count"]),
            )
            connection.execute(
                "INSERT INTO public_procurement.bid_eligibility_requirement_sets "
                "(extraction_id,expression,unresolved_candidates) VALUES (%s,%s,%s)",
                (extraction_id, Jsonb(result["expression"]), Jsonb(result["unresolved_candidates"])),
            )
            for item in result["requirements"]:
                requirement_id = uuid5(NAMESPACE_URL, f"teoria:{extraction_id}:{item['id']}")
                connection.execute(
                    "INSERT INTO public_procurement.bid_eligibility_requirements "
                    "(requirement_id,extraction_id,local_id,notice_number,notice_order,requirement_type,operator,value,original_text,holder_scope,reference_date_type,mandatory,review_status,confidence) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (requirement_id, extraction_id, item["id"], notice["notice_number"],
                     notice["notice_order"], item["type"], item["operator"], Jsonb(item["value"]),
                     item["original_text"], item["holder_scope"], item["reference_date_type"],
                     item["mandatory"], item["review_status"], item["confidence"]),
                )
                for evidence in item["evidence"]:
                    connection.execute(
                        "INSERT INTO public_procurement.bid_eligibility_requirement_evidence "
                        "(evidence_id,requirement_id,source_type,source_id,document_id,block_id,page_number,section,excerpt) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (uuid4(), requirement_id, evidence["source_type"], evidence["source_id"],
                         evidence["document_id"], evidence["block_id"], evidence["page"],
                         evidence["section"], evidence["excerpt"]),
                    )
        return True

    @staticmethod
    def _upsert_many(connection: Any, table: str, rows: list[dict[str, Any]],
                     keys: tuple[str, ...]) -> None:
        if not rows:
            return
        columns = tuple(rows[0])
        if any(tuple(row) != columns for row in rows):
            raise ValueError(f"all rows for {table} must have identical columns")
        assignments = [column for column in columns if column not in keys]
        placeholders = ", ".join(f"%({column})s" for column in columns)
        conflict = ", ".join(keys)
        update = ", ".join(
            [*(f"{column}=EXCLUDED.{column}" for column in assignments), "updated_at=now()"]
        )
        changed = " OR ".join(
            f"{table}.{column} IS DISTINCT FROM EXCLUDED.{column}"
            for column in assignments
        )
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {update} WHERE {changed}"
        )
        with connection.cursor() as cursor:
            cursor.executemany(statement, rows)

    def get_checkpoint(self, pipeline_id: str) -> date | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT cursor_date FROM ingestion.pipeline_checkpoints WHERE pipeline_id=%s",
                (pipeline_id,),
            ).fetchone()
        return row[0] if row else None

    def update_checkpoint(self, pipeline_id: str, cursor_date: date,
                          execution_id: UUID) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO ingestion.pipeline_checkpoints "
                "(pipeline_id, cursor_date, execution_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (pipeline_id) DO UPDATE SET cursor_date=EXCLUDED.cursor_date, "
                "execution_id=EXCLUDED.execution_id, updated_at=now()",
                (pipeline_id, cursor_date, execution_id),
            )
