"""Recovery safety against an explicitly configured, disposable PostgreSQL DB."""

import gzip
import hashlib
import io
import json
import os
from dataclasses import replace

import psycopg
import pytest
from psycopg import sql
from teoria.features.goods_notice_collection import backup_restore as recovery
from teoria.integrations.data_operations.persistence.connection import connect

DATABASE_URL = os.environ.get("TEORIA_TEST_GOODS_RESTORE_DATABASE_URL")
TABLES = (
    "goods_notice_attachment_refs",
    "goods_notice_observations",
    "goods_notice_versions",
    "goods_notice_import_batches",
    "bid_notice_latest_versions",
    "bid_notice_lineage_summaries",
    "bid_notices",
)


def test_copy_values_preserve_korean_json_escapes():
    value = '{"파일":"한글\\n.txt","url":"https://example.test/?a=1&b=2"}'
    encoded = value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
    assert recovery.copy_value(encoded) == value
    assert recovery.copy_value(r"\N") is None
    assert recovery.copy_value(r"\\N") == r"\N"


def test_copy_rejects_sql_after_terminator():
    with pytest.raises(ValueError, match="after COPY terminator"):
        recovery.read_batch(
            io.BytesIO(b"\\.\nDROP TABLE anything;\n"),
            [
                "work_type",
                "notice_number",
                "notice_order",
                "source_payload",
                "source_record_hash",
            ],
        )


@pytest.fixture
async def database():
    if not DATABASE_URL:
        pytest.skip("Disposable goods recovery DB is not configured")
    async with connect(DATABASE_URL, autocommit=True) as connection:
        name = (
            await (await connection.execute("SELECT current_database()")).fetchone()
        )[0]
        assert name == "teoria_goods_restore_fixtures", (
            "Refusing to clear a non-fixture DB"
        )
        clear = sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
            sql.SQL(",").join(
                sql.Identifier("public_procurement", name) for name in TABLES
            )
        )
        await connection.execute(clear)
        yield connection
        await connection.execute(clear)


@pytest.fixture
async def archive_factory(database, tmp_path):
    columns = [
        row[0]
        for row in await (
            await database.execute(
                "SELECT attname FROM pg_attribute WHERE attrelid='public_procurement.bid_notices'::regclass "
                "AND attnum>0 AND NOT attisdropped ORDER BY attnum"
            )
        ).fetchall()
    ]

    def create(*, work_type="goods", wrong_hash=False, suffix=b"", count=2):
        lines = [
            f"COPY public_procurement.bid_notices ({', '.join(columns)}) FROM stdin;\n".encode()
        ]
        for i in range(count):
            payload = {
                "bidNtceNo": "fixture",
                "bidNtceOrd": f"{i:03}",
                "ntceSpecDocUrl1": f"https://example.test/{i}?a=1&b=2",
                "ntceSpecFileNm1": "한글.txt",
            }
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            digest = hashlib.sha256(canonical.encode()).hexdigest()
            row = {key: None for key in columns}
            row.update(
                notice_number="fixture",
                notice_order=f"{i:03}",
                work_type=work_type,
                source_record_hash="0" * 64 if wrong_hash else digest,
                source_payload=canonical,
                notice_name="한글 공고",
                notice_published_at=f"2026-01-0{i + 1} 00:00:00+00",
                created_at="2026-01-01 00:00:00+00",
                updated_at="2026-01-01 00:00:00+00",
                enrichment_checked_at="2026-01-01 00:00:00+00",
                enrichment_claimed_at="2026-01-01 00:00:00+00",
                lineage_root_notice_number="fixture",
            )

            def encode(value):
                if value is None:
                    return r"\N"
                return (
                    value.replace("\\", "\\\\")
                    .replace("\t", "\\t")
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                )

            lines.append(
                ("\t".join(encode(row[key]) for key in columns) + "\n").encode()
            )
        lines.append(b"\\.\n" + suffix)
        path = tmp_path / "fixture.sql.gz"
        with gzip.open(path, "wb") as stream:
            stream.write(b"".join(lines))
        manifest = recovery.BackupManifest(
            "synthetic-fixture", "1" * 64, recovery.file_sha256(path), count, count
        )
        return path, manifest

    return create


async def run_restore(path, manifest):
    return await recovery.restore_backup(
        DATABASE_URL or "",
        path,
        manifest,
        expected_database="teoria_goods_restore_fixtures",
    )


async def count(database, table):
    return (
        await (
            await database.execute(
                sql.SQL("SELECT count(*) FROM public_procurement.{}").format(
                    sql.Identifier(table)
                )
            )
        ).fetchone()
    )[0]


async def test_restore_preserves_urls_revisions_and_resets_claims(
    database, archive_factory
):
    path, manifest = archive_factory()
    result = await run_restore(path, manifest)
    assert result["notice_count"] == result["attachment_count"] == 2
    assert not result["already_imported"]
    assert await (
        await database.execute(
            "SELECT notice_order FROM public_procurement.bid_notice_latest_versions"
        )
    ).fetchone() == ("001",)
    assert await (
        await database.execute(
            "SELECT bool_and(enrichment_checked_at IS NULL AND enrichment_claimed_at IS NULL) "
            "FROM public_procurement.bid_notices"
        )
    ).fetchone() == (True,)
    assert await (
        await database.execute(
            "SELECT source_url,file_name FROM public_procurement.goods_notice_attachment_refs ORDER BY notice_order"
        )
    ).fetchall() == [
        ("https://example.test/0?a=1&b=2", "한글.txt"),
        ("https://example.test/1?a=1&b=2", "한글.txt"),
    ]
    assert await (
        await database.execute(
            "SELECT bool_and(observation_kind='backup_import' AND execution_id IS NULL AND source_observed_at IS NULL) "
            "FROM public_procurement.goods_notice_observations"
        )
    ).fetchone() == (True,)
    assert await (
        await database.execute(
            "SELECT lineage_count FROM public_procurement.bid_notice_lineage_summaries"
        )
    ).fetchone() == (2,)
    assert await run_restore(path, manifest) == {**result, "already_imported": True}
    assert await count(database, "goods_notice_observations") == 2
    with pytest.raises(ValueError, match="different provenance"):
        await run_restore(path, replace(manifest, backup_label="different"))


@pytest.mark.parametrize(
    "case",
    [
        "checksum",
        "row_count",
        "attachment_count",
        "non_goods",
        "hash",
        "trailing_sql",
        "database",
    ],
)
async def test_rejected_import_leaves_no_rows(database, archive_factory, case):
    path, manifest = archive_factory(
        work_type="service" if case == "non_goods" else "goods",
        wrong_hash=case == "hash",
        suffix=b"SELECT 1;\n" if case == "trailing_sql" else b"",
    )
    if case == "checksum":
        manifest = replace(manifest, subset_sha256="0" * 64)
    if case == "row_count":
        manifest = replace(manifest, notice_count=3)
    if case == "attachment_count":
        manifest = replace(manifest, attachment_count=3)
    with pytest.raises(ValueError):
        await recovery.restore_backup(
            DATABASE_URL or "",
            path,
            manifest,
            expected_database="wrong_db"
            if case == "database"
            else "teoria_goods_restore_fixtures",
        )
    for table in TABLES:
        assert await count(database, table) == 0


async def test_existing_notices_are_not_overwritten(database, archive_factory):
    path, manifest = archive_factory()
    await database.execute(
        "INSERT INTO public_procurement.bid_notices (notice_number,notice_order,work_type,source_record_hash,source_payload) VALUES ('existing','000','goods',%s,'{}')",
        ("2" * 64,),
    )
    with pytest.raises(ValueError, match="empty notice"):
        await run_restore(path, manifest)
    assert await count(database, "bid_notices") == 1
    assert await count(database, "goods_notice_versions") == 0


async def test_late_failure_restores_rows_and_trigger_state(
    database, archive_factory, monkeypatch
):
    path, manifest = archive_factory()

    async def fail(connection):
        assert await count(connection, "goods_notice_attachment_refs") == 2
        raise RuntimeError("synthetic failure after evidence writes")

    monkeypatch.setattr(recovery, "rebuild_projections", fail)
    with pytest.raises(RuntimeError, match="after evidence"):
        await run_restore(path, manifest)
    for table in TABLES:
        assert await count(database, table) == 0
    assert {
        row[1]
        for row in await (
            await database.execute(
                "SELECT tgname,tgenabled FROM pg_trigger WHERE tgrelid='public_procurement.bid_notices'::regclass AND NOT tgisinternal"
            )
        ).fetchall()
    } == {"O"}


@pytest.mark.parametrize("table", TABLES[:4])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
async def test_evidence_is_append_only(database, archive_factory, table, verb):
    await run_restore(*archive_factory())
    statement = sql.SQL(
        "DELETE FROM public_procurement.{}"
        if verb == "DELETE"
        else "UPDATE public_procurement.{} SET notice_number=notice_number"
    )
    if verb == "UPDATE" and table == "goods_notice_import_batches":
        statement = sql.SQL(
            "UPDATE public_procurement.{} SET backup_label=backup_label"
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        await database.execute(statement.format(sql.Identifier(table)))


async def test_versions_keep_removed_attachments_and_observation_provenance(
    database, archive_factory
):
    await run_restore(*archive_factory())
    payload = {"bidNtceNo": "fixture", "bidNtceOrd": "000"}
    digest = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    await database.execute(
        "INSERT INTO public_procurement.goods_notice_versions VALUES ('fixture','000',%s,%s::jsonb)",
        (digest, json.dumps(payload)),
    )
    assert await count(database, "goods_notice_versions") == 3
    assert await count(database, "goods_notice_attachment_refs") == 2
    assert await (
        await database.execute(
            "SELECT count(*) FROM public_procurement.goods_notice_attachment_refs WHERE source_record_hash=%s",
            (digest,),
        )
    ).fetchone() == (0,)
    with pytest.raises(psycopg.errors.CheckViolation):
        await database.execute(
            "INSERT INTO public_procurement.goods_notice_observations (notice_number,notice_order,source_record_hash,observation_kind) VALUES ('fixture','000',%s,'api_fetch')",
            (digest,),
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await database.execute(
            "INSERT INTO public_procurement.goods_notice_attachment_refs VALUES ('fixture','000',%s,1,'https://example.test/orphan',NULL)",
            ("0" * 64,),
        )
