"""Atomic, bounded-memory recovery of an audited goods-only COPY archive."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import NAMESPACE_URL, uuid5

from psycopg import sql

from teoria.integrations.data_operations.persistence.connection import connect

PROJECTION_TRIGGERS = (
    "bid_notices_set_lineage_fields",
    "bid_notices_sync_latest_version",
    "bid_notices_refresh_lineage_summary",
)


@dataclass(frozen=True)
class BackupManifest:
    backup_label: str
    archive_sha256: str
    subset_sha256: str
    notice_count: int
    attachment_count: int

    def __post_init__(self):
        if not self.backup_label or any(
            not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (self.archive_sha256, self.subset_sha256)
        ):
            raise ValueError("Invalid backup provenance")
        if self.notice_count < 1 or self.attachment_count < 0:
            raise ValueError("Invalid expected counts")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_value(value: str) -> str | None:
    if value == r"\N":
        return None

    def replacement(match):
        token = match[1]
        if token[0].isdigit():
            return chr(int(token, 8))
        return {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}.get(
            token, token
        )

    return re.sub(r"\\([0-7]{1,3}|.)", replacement, value)


def read_header(stream: BinaryIO) -> list[str]:
    header = stream.readline().decode("ascii")
    match = re.fullmatch(
        r"COPY public_procurement\.bid_notices \(([a-z_, ]+)\) FROM stdin;\n",
        header,
    )
    if not match:
        raise ValueError("Expected a standalone bid_notices COPY archive")
    columns = match[1].split(", ")
    if len(set(columns)) != len(columns):
        raise ValueError("Duplicate COPY columns")
    return columns


def read_batch(stream: BinaryIO, columns: list[str]) -> tuple[bytes, int, int, bool]:
    """Run gzip and JSON work in one bounded thread call; never log row contents."""
    indexes = {
        key: columns.index(key)
        for key in (
            "work_type",
            "notice_number",
            "notice_order",
            "source_payload",
            "source_record_hash",
        )
    }
    lines = stream.readlines(1024 * 1024)
    if not lines:
        raise ValueError("COPY terminator is missing")
    rows = attachments = 0
    output = []
    terminated = False
    for line in lines:
        if line == b"\\.\n":
            if terminated:
                raise ValueError("Multiple COPY terminators")
            terminated = True
            continue
        if terminated:
            raise ValueError("Unexpected data after COPY terminator")
        values = line.rstrip(b"\n").decode("utf-8").split("\t")
        if len(values) != len(columns):
            raise ValueError("COPY row width mismatch")
        data = {key: copy_value(values[index]) for key, index in indexes.items()}
        if data["work_type"] != "goods":
            raise ValueError("Archive includes a non-goods notice")
        payload = json.loads(data["source_payload"] or "null")
        if not isinstance(payload, dict):
            raise TypeError("Invalid source payload")
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if hashlib.sha256(canonical.encode()).hexdigest() != data["source_record_hash"]:
            raise ValueError("Source payload hash mismatch")
        if (
            payload.get("bidNtceNo") != data["notice_number"]
            or payload.get("bidNtceOrd") != data["notice_order"]
        ):
            raise ValueError("Source identity mismatch")
        for slot in range(1, 11):
            url = payload.get(f"ntceSpecDocUrl{slot}")
            if url is not None and not isinstance(url, str):
                raise TypeError("Invalid attachment URL type")
            attachments += bool(url and url.strip())
        output.append(line)
        rows += 1
    if terminated and stream.read(1):
        raise ValueError("Unexpected data after COPY terminator")
    return b"".join(output), rows, attachments, terminated


async def restore_backup(
    database_url: str,
    subset_path: Path,
    manifest: BackupManifest,
    *,
    expected_database: str,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Restore into an empty notice catalog; all DB changes share one transaction.

    The caller supplies provenance from an independently verified source backup.
    This function checks the subset bytes, every original JSON hash and identity,
    counts, schema and target DB before committing. It never contacts a provider.
    """
    if not expected_database:
        raise ValueError("An explicit target database name is required")
    if await asyncio.to_thread(file_sha256, subset_path) != manifest.subset_sha256:
        raise ValueError("Subset checksum mismatch")
    batch_id = uuid5(
        NAMESPACE_URL, "teoria:goods-notice-import:" + manifest.subset_sha256
    )
    async with (
        connect(database_url) as connection,
        connection.transaction(),
    ):
        actual_database = (
            await (await connection.execute("SELECT current_database()")).fetchone()
        )[0]
        if actual_database != expected_database:
            raise ValueError("Target database does not match the explicit expectation")
        await connection.execute("SET LOCAL lock_timeout = '5s'")
        await connection.execute(
            "LOCK TABLE public_procurement.bid_notices, "
            "public_procurement.bid_notice_latest_versions, "
            "public_procurement.bid_notice_lineage_summaries, "
            "public_procurement.goods_notice_import_batches, "
            "public_procurement.goods_notice_versions, "
            "public_procurement.goods_notice_observations, "
            "public_procurement.goods_notice_attachment_refs IN ACCESS EXCLUSIVE MODE"
        )
        prior = await (
            await connection.execute(
                "SELECT backup_label,archive_sha256,notice_count,attachment_count "
                "FROM public_procurement.goods_notice_import_batches WHERE subset_sha256=%s",
                (manifest.subset_sha256,),
            )
        ).fetchone()
        if prior:
            if prior != (
                manifest.backup_label,
                manifest.archive_sha256,
                manifest.notice_count,
                manifest.attachment_count,
            ):
                raise ValueError("Existing import has different provenance or counts")
            return {
                "batch_id": str(batch_id),
                "notice_count": prior[2],
                "attachment_count": prior[3],
                "already_imported": True,
            }
        for table in (
            "bid_notices",
            "bid_notice_latest_versions",
            "bid_notice_lineage_summaries",
            "goods_notice_import_batches",
            "goods_notice_versions",
            "goods_notice_observations",
            "goods_notice_attachment_refs",
        ):
            populated = (
                await (
                    await connection.execute(
                        sql.SQL(
                            "SELECT EXISTS (SELECT 1 FROM public_procurement.{})"
                        ).format(sql.Identifier(table))
                    )
                ).fetchone()
            )[0]
            if populated:
                raise ValueError(
                    "Recovery requires an empty notice catalog and evidence tables"
                )
        triggers = await (
            await connection.execute(
                "SELECT tgname,tgenabled FROM pg_trigger "
                "WHERE tgrelid='public_procurement.bid_notices'::regclass AND NOT tgisinternal"
            )
        ).fetchall()
        if set(triggers) != {(name, "O") for name in PROJECTION_TRIGGERS}:
            raise ValueError(
                "Notice triggers differ from the reviewed recovery contract"
            )
        await connection.execute(
            "CREATE TEMP TABLE goods_notice_restore_stage "
            "(LIKE public_procurement.bid_notices INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        stream = await asyncio.to_thread(gzip.open, subset_path, "rb")
        rows = attachment_count = 0
        try:
            columns = await asyncio.to_thread(read_header, stream)
            actual_columns = [
                row[0]
                for row in await (
                    await connection.execute(
                        "SELECT attname FROM pg_attribute WHERE attrelid='public_procurement.bid_notices'::regclass "
                        "AND attnum>0 AND NOT attisdropped ORDER BY attnum"
                    )
                ).fetchall()
            ]
            if columns != actual_columns:
                raise ValueError(
                    "COPY columns differ from the target schema; review the migration"
                )
            column_sql = sql.SQL(",").join(map(sql.Identifier, columns))
            async with (
                connection.cursor() as cursor,
                cursor.copy(
                    sql.SQL("COPY goods_notice_restore_stage ({}) FROM STDIN").format(
                        column_sql
                    )
                ) as copy,
            ):
                done = False
                while not done:
                    block, count, refs, done = await asyncio.to_thread(
                        read_batch, stream, columns
                    )
                    await copy.write(block)
                    rows += count
                    attachment_count += refs
                    if progress:
                        progress(
                            {
                                "phase": "stage",
                                "notices": rows,
                                "attachment_refs": attachment_count,
                            }
                        )
        finally:
            await asyncio.to_thread(stream.close)
        if (rows, attachment_count) != (
            manifest.notice_count,
            manifest.attachment_count,
        ):
            raise ValueError("Archive counts differ from the manifest")
        await connection.execute(
            "UPDATE goods_notice_restore_stage SET enrichment_checked_at=NULL,enrichment_claimed_at=NULL"
        )
        for name in PROJECTION_TRIGGERS:
            await connection.execute(
                sql.SQL(
                    "ALTER TABLE public_procurement.bid_notices DISABLE TRIGGER {}"
                ).format(sql.Identifier(name))
            )
        if progress:
            progress({"phase": "catalog", "notices": rows})
        await connection.execute(
            sql.SQL(
                "INSERT INTO public_procurement.bid_notices ({}) SELECT {} FROM goods_notice_restore_stage"
            ).format(column_sql, column_sql)
        )
        if progress:
            progress({"phase": "evidence", "notices": rows})
        await connection.execute(
            "INSERT INTO public_procurement.goods_notice_import_batches "
            "(batch_id,backup_label,archive_sha256,subset_sha256,notice_count,attachment_count) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                batch_id,
                manifest.backup_label,
                manifest.archive_sha256,
                manifest.subset_sha256,
                rows,
                attachment_count,
            ),
        )
        await connection.execute(
            "INSERT INTO public_procurement.goods_notice_versions "
            "SELECT notice_number,notice_order,source_record_hash,source_payload FROM goods_notice_restore_stage"
        )
        await connection.execute(
            "INSERT INTO public_procurement.goods_notice_observations "
            "(notice_number,notice_order,source_record_hash,observation_kind,import_batch_id) "
            "SELECT notice_number,notice_order,source_record_hash,'backup_import',%s FROM goods_notice_restore_stage",
            (batch_id,),
        )
        await connection.execute(
            "INSERT INTO public_procurement.goods_notice_attachment_refs "
            "SELECT n.notice_number,n.notice_order,n.source_record_hash,s.slot::smallint, "
            "n.source_payload->>('ntceSpecDocUrl'||s.slot), "
            "n.source_payload->>('ntceSpecFileNm'||s.slot) "
            "FROM goods_notice_restore_stage n CROSS JOIN generate_series(1,10) s(slot) "
            "WHERE btrim(COALESCE(n.source_payload->>('ntceSpecDocUrl'||s.slot),''))<>''"
        )
        await rebuild_projections(connection)
        for name in PROJECTION_TRIGGERS:
            await connection.execute(
                sql.SQL(
                    "ALTER TABLE public_procurement.bid_notices ENABLE TRIGGER {}"
                ).format(sql.Identifier(name))
            )
        counts = await (
            await connection.execute(
                "SELECT (SELECT count(*) FROM public_procurement.bid_notices), "
                "(SELECT count(*) FROM public_procurement.goods_notice_versions), "
                "(SELECT count(*) FROM public_procurement.goods_notice_observations), "
                "(SELECT count(*) FROM public_procurement.goods_notice_attachment_refs)"
            )
        ).fetchone()
        if counts != (rows, rows, rows, attachment_count):
            raise ValueError("Restored evidence counts differ from the manifest")
    return {
        "batch_id": str(batch_id),
        "notice_count": rows,
        "attachment_count": attachment_count,
        "already_imported": False,
    }


async def rebuild_projections(connection) -> None:
    """Rebuild the two existing projections with their original ordering rules."""
    await connection.execute(
        "INSERT INTO public_procurement.bid_notice_latest_versions (notice_number,notice_order) "
        "SELECT DISTINCT ON (notice_number) notice_number,notice_order "
        "FROM public_procurement.bid_notices ORDER BY notice_number, "
        "CASE WHEN notice_order ~ '^[0-9]+$' THEN notice_order::numeric END DESC NULLS LAST, "
        "notice_order DESC,notice_published_at DESC NULLS LAST"
    )
    await connection.execute(
        "INSERT INTO public_procurement.bid_notice_lineage_summaries "
        "(root_number,lineage_count,latest_bid_notice_id,lineage_notices) "
        "SELECT COALESCE(lineage_root_notice_number,notice_number),count(*)::integer, "
        "(array_agg(notice_number||':'||notice_order ORDER BY notice_published_at DESC NULLS LAST,notice_number DESC))[1], "
        "jsonb_agg(jsonb_build_object('bid_notice_id',notice_number||':'||notice_order, "
        "'notice_kind',CASE WHEN notice_kind_name='재공고' OR is_re_notice THEN 're_notice' "
        "WHEN notice_kind_name='변경공고' THEN 'correction' WHEN notice_kind_name='취소공고' THEN 'cancellation' "
        "WHEN notice_kind_name='등록공고' THEN 'original' ELSE 'unknown' END, "
        "'notice_published_at',notice_published_at) ORDER BY notice_published_at,notice_number,notice_order)::text "
        "FROM public_procurement.bid_notices GROUP BY COALESCE(lineage_root_notice_number,notice_number)"
    )
