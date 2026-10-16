"""Pipeline-owned law ingestion, snapshot and reparse behavior against PostgreSQL."""

import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria_pipelines.domains.legal_information.laws.models import (
    LawTarget,
    LawVersion,
    LawResponse,
    LawCatalog,
)
from teoria_pipelines.domains.legal_information.laws.parsing import parse_law
from teoria_pipelines.domains.legal_information.laws.repository import LawRepository
from teoria_pipelines.models import CollectionWindow
from teoria_pipelines.persistence import PostgresStore

DATABASE_URL = os.environ.get("TEORIA_TEST_DATA_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="TEORIA_TEST_DATA_DATABASE_URL is not set"
)
PIPELINES = Path(__file__).parents[2]


@pytest.fixture
async def law_setup():
    store = PostgresStore(DATABASE_URL or "")
    await store.apply_migrations(PIPELINES / "database/migrations")
    run_id = uuid4()
    await store.start_run(
        run_id, "law_test", CollectionWindow(date(2026, 7, 1), date(2026, 7, 1))
    )
    law_id = str(10000000 + uuid4().int % 10000000)
    target = LawTarget(id="test_" + uuid4().hex, name="테스트 법률", law_id=law_id)
    v = LawVersion(
        law_id,
        "100",
        date(2026, 7, 1),
        "테스트 법률",
        date(2026, 1, 1),
        "999",
        "일부개정",
        {"현행연혁코드": "현행"},
    )
    raw = (
        (PIPELINES / "tests/fixtures/legal_information/law_body.xml")
        .read_bytes()
        .replace(b"000001", law_id.encode())
    )
    r = LawResponse(
        "get_law_version",
        {"MST": "100", "efYd": "20260701"},
        datetime.now(timezone.utc),
        "text/xml",
        raw,
    )
    repo = LawRepository(DATABASE_URL or "")
    await repo.register_catalog(target, LawCatalog(law_id, [v], []))
    return repo, run_id, target, v, r


async def test_snapshots_deduplicate_and_changed_source_keeps_previous_content(
    law_setup,
):
    repo, run, target, v, r = law_setup
    source_hash = await repo.save_raw(run, r)
    parsed = parse_law(r.raw_body, v)
    first = await repo.save_snapshot(parsed, r, source_hash)
    assert (await repo.save_snapshot(parsed, r, source_hash)) == first
    changed = replace(
        r,
        raw_body=r.raw_body.replace("첫 번째 목".encode(), "변경된 목".encode()),
        fetched_at=datetime.now(timezone.utc),
    )
    changed_hash = await repo.save_raw(run, changed)
    second = await repo.save_snapshot(
        parse_law(changed.raw_body, v), changed, changed_hash
    )
    assert first != second
    with psycopg.connect(DATABASE_URL) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            == 2
        )
        assert (
            c.execute(
                "SELECT content FROM legal_information.law_provision WHERE snapshot_id=%s AND kind='item'",
                (first,),
            ).fetchone()[0]
            == "첫 번째 목"
        )
        assert (
            c.execute(
                "SELECT latest_snapshot_id FROM legal_information.law_version WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            == second
        )
    rows = await repo.get_provisions(v.law_id, v.mst, v.effective_date, "24의2")
    assert len(rows) == 5
    assert next(p["content"] for p in rows if p["kind"] == "item") == "변경된 목"
    assert (
        await repo.archived_response((await repo.stored_versions(target.id))[0])
    ).raw_body == changed.raw_body


async def test_failed_structural_write_rolls_back_snapshot_and_pointer(law_setup):
    repo, run, target, v, r = law_setup
    source_hash = await repo.save_raw(run, r)
    parsed = parse_law(r.raw_body, v)
    parsed.provisions[1]["parent_path"] = "missing_parent"
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await repo.save_snapshot(parsed, r, source_hash)
    with psycopg.connect(DATABASE_URL) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            c.execute(
                "SELECT latest_snapshot_id FROM legal_information.law_version WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            is None
        )


async def test_reparse_new_parser_uses_archive_and_preserves_old_revision(law_setup):
    repo, run, target, v, r = law_setup
    h = await repo.save_raw(run, r)
    parsed = parse_law(r.raw_body, v)
    old = await repo.save_snapshot(parsed, r, h)
    archived = await repo.archived_response((await repo.stored_versions(target.id))[0])
    reparsed = parse_law(archived.raw_body, v)
    reparsed.parser_version = "test_new_parser"
    new = await repo.save_snapshot(reparsed, archived, h)
    assert old != new
    with psycopg.connect(DATABASE_URL) as c:
        assert (
            c.execute(
                "SELECT count(*) FROM legal_information.law_snapshot WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            == 2
        )
    assert (await repo.stored_versions(target.id))[0][
        "parser_version"
    ] == "test_new_parser"


async def test_incremental_collection_keeps_new_historical_and_future_slices(law_setup):
    repo, run, target, v, r = law_setup
    await repo.save_snapshot(parse_law(r.raw_body, v), r, (await repo.save_raw(run, r)))
    historical = replace(v, listing={"현행연혁코드": "연혁"})
    new = replace(
        v, mst="90", effective_date=date(2025, 1, 1), listing={"현행연혁코드": "연혁"}
    )
    future = replace(
        v, effective_date=date(2027, 1, 1), listing={"현행연혁코드": "시행예정"}
    )
    catalog = LawCatalog(v.law_id, [historical, new, future], [])
    await repo.register_catalog(target, catalog)
    selected = await repo.select_versions(
        catalog, reconcile_all=False, today=date(2026, 10, 12)
    )
    assert [v.key for v in selected] == [new.key, future.key]
    assert (
        len(
            (
                await repo.select_versions(
                    catalog, reconcile_all=True, today=date(2026, 10, 12)
                )
            )
        )
        == 3
    )


async def test_provision_lookup_preserves_numeric_sibling_order(law_setup):
    repo, run, target, v, r = law_setup
    extra = "".join(
        f"<호><호번호>{i}.</호번호><호내용>순서 {i}</호내용></호>" for i in range(2, 13)
    ).encode()
    raw = r.raw_body.replace(
        b"</" + "항".encode() + b">", extra + b"</" + "항".encode() + b">", 1
    )
    r = replace(r, raw_body=raw)
    await repo.save_snapshot(parse_law(raw, v), r, (await repo.save_raw(run, r)))
    rows = await repo.get_provisions(v.law_id, v.mst, v.effective_date, "24의2")
    assert [p["number"] for p in rows if p["kind"] == "subparagraph"] == [
        f"{i}." for i in range(1, 13)
    ]
