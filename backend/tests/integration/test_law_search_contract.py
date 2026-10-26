"""Law ingestion output consumed by the search reader and Runtime role."""

import os
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from teoria.features.legal_information.collection.models import (
    LawTarget,
    LawVersion,
    LawResponse,
    LawCatalog,
)
from teoria.features.legal_information.collection.parsing import parse_law
from teoria.features.legal_information.collection.repository import LawRepository
from teoria.integrations.data_operations.models import CollectionWindow
from teoria.integrations.data_operations.persistence import PostgresStore

DATABASE_URL = os.environ.get("TEORIA_TEST_DATA_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="TEORIA_TEST_DATA_DATABASE_URL is not set"
)
ROOT = (Path(__file__).resolve().parents[3])


@pytest.fixture
async def law_setup():
    store = PostgresStore(DATABASE_URL or "")
    await store.apply_migrations(ROOT / "backend/migrations/data")
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
        (ROOT / "backend/tests/fixtures/legal_information/law_body.xml")
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


def test_runtime_has_no_law_archive_access(law_setup):
    with psycopg.connect(DATABASE_URL) as c:
        assert (
            c.execute(
                "SELECT has_table_privilege('teoria_runtime','legal_information.law_snapshot','SELECT')"
            ).fetchone()[0]
            is False
        )
        assert (
            c.execute(
                "SELECT has_table_privilege('teoria_runtime','legal_information.law_search_documents','SELECT')"
            ).fetchone()[0]
            is True
        )
        assert (
            c.execute(
                "SELECT has_table_privilege('teoria_runtime','ingestion.law_raw_payloads','SELECT')"
            ).fetchone()[0]
            is False
        )


async def test_keyword_search_finds_descendants_and_pins_old_snapshot(law_setup):
    from teoria.features.legal_information.search import (
        LawSearchReader,
        LawSearchRequest,
    )

    repo, run, target, v, r = law_setup
    r = replace(
        r, raw_body=r.raw_body.replace("첫 번째 목".encode(), "고유검색문구".encode())
    )
    first = await repo.save_snapshot(
        parse_law(r.raw_body, v), r, (await repo.save_raw(run, r))
    )
    reader = LawSearchReader(DATABASE_URL)
    result = await reader.search(
        LawSearchRequest(
            query="고유검색문구",
            match="all",
            law_id=v.law_id,
            assessment_date=date(2026, 7, 1),
        )
    )
    assert result["items"][0]["number"] == "24의2"
    assert result["items"][0]["snapshot_id"] == first
    assert result["legal_applicability_confirmed"] is False
    path = result["items"][0]["path"]
    changed = replace(
        r,
        raw_body=r.raw_body.replace("고유검색문구".encode(), "변경된 목".encode()),
        fetched_at=datetime.now(timezone.utc),
    )
    second = await repo.save_snapshot(
        parse_law(changed.raw_body, v), changed, (await repo.save_raw(run, changed))
    )
    assert (
        await reader.search(
            LawSearchRequest(query="고유검색문구", match="all", law_id=v.law_id)
        )
    )["items"] == []
    assert "고유검색문구" in (await reader.get_document(first, path))["content"]
    assert "변경된 목" in (await reader.get_document(second, path))["content"]


async def test_keyword_search_does_not_mix_future_versions_or_treat_wildcards_as_query(
    law_setup,
):
    from teoria.features.legal_information.search import (
        LawSearchReader,
        LawSearchRequest,
    )

    repo, run, target, v, r = law_setup
    (
        await repo.save_snapshot(
            parse_law(r.raw_body, v), r, (await repo.save_raw(run, r))
        )
    )
    future = replace(v, mst="101", effective_date=date(2027, 1, 1))
    (await repo.register_catalog(target, LawCatalog(v.law_id, [v, future], [])))
    future_r = replace(
        r,
        query={"MST": "101", "efYd": "20270101"},
        raw_body=r.raw_body.replace(b"20260701", b"20270101"),
        fetched_at=datetime.now(timezone.utc),
    )
    (
        await repo.save_snapshot(
            parse_law(future_r.raw_body, future),
            future_r,
            (await repo.save_raw(run, future_r)),
        )
    )
    reader = LawSearchReader(DATABASE_URL)
    hits = (
        await reader.search(
            LawSearchRequest(
                query="테스트", law_id=v.law_id, assessment_date=date(2026, 10, 12)
            )
        )
    )["items"]
    assert hits and {h["mst"] for h in hits} == {"100"}
    hits = (
        await reader.search(
            LawSearchRequest(query="테스트", law_id=v.law_id, version_scope="all")
        )
    )["items"]
    assert {h["mst"] for h in hits} == {"100", "101"}
    assert (await reader.search(LawSearchRequest(query="_%", law_id=v.law_id)))[
        "items"
    ] == []


async def test_repeal_does_not_resurrect_earlier_version(law_setup):
    from teoria.features.legal_information.search import (
        LawSearchReader,
        LawSearchRequest,
    )

    repo, run, target, v, r = law_setup
    (
        await repo.save_snapshot(
            parse_law(r.raw_body, v), r, (await repo.save_raw(run, r))
        )
    )
    repeal = replace(
        v, mst="102", effective_date=date(2026, 10, 1), amendment_type="폐지"
    )
    (await repo.register_catalog(target, LawCatalog(v.law_id, [v, repeal], [])))
    repeal_r = replace(
        r,
        query={"MST": "102", "efYd": "20261001"},
        raw_body=r.raw_body.replace(b"20260701", b"20261001"),
    )
    (
        await repo.save_snapshot(
            parse_law(repeal_r.raw_body, repeal),
            repeal_r,
            (await repo.save_raw(run, repeal_r)),
        )
    )
    reader = LawSearchReader(DATABASE_URL)
    assert (
        await reader.search(
            LawSearchRequest(
                query="테스트", law_id=v.law_id, assessment_date=date(2026, 10, 12)
            )
        )
    )["items"] == []
    assert (
        await reader.search(
            LawSearchRequest(
                query="테스트", law_id=v.law_id, assessment_date=date(2026, 9, 30)
            )
        )
    )["items"]


async def test_keyword_search_reports_missing_new_version_instead_of_falling_back(
    law_setup,
):
    from teoria.features.legal_information.search import (
        LawSearchReader,
        LawSearchRequest,
    )

    repo, run, target, v, r = law_setup
    (
        await repo.save_snapshot(
            parse_law(r.raw_body, v), r, (await repo.save_raw(run, r))
        )
    )
    newer = replace(v, mst="103", effective_date=date(2026, 10, 1))
    (await repo.register_catalog(target, LawCatalog(v.law_id, [v, newer], [])))
    result = await LawSearchReader(DATABASE_URL).search(
        LawSearchRequest(
            query="테스트", law_id=v.law_id, assessment_date=date(2026, 10, 12)
        )
    )
    assert result["items"] == []
    assert result["unavailable_versions"][0]["mst"] == "103"


async def test_runtime_role_reads_search_projection_without_base_tables(law_setup):
    repo, run, target, v, r = law_setup
    (
        await repo.save_snapshot(
            parse_law(r.raw_body, v), r, (await repo.save_raw(run, r))
        )
    )
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("SET ROLE teoria_runtime")
        assert (
            c.execute(
                "SELECT count(*) FROM legal_information.law_search_documents WHERE law_id=%s",
                (v.law_id,),
            ).fetchone()[0]
            > 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM legal_information.law_snapshot LIMIT 1")
