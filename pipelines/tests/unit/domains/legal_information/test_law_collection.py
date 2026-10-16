from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from teoria_pipelines.domains.legal_information.laws.client import (
    MolegLawClient,
    redact_xml,
)
from teoria_pipelines.domains.legal_information.laws.models import (
    LawTarget,
    LawResponse,
    LawVersion,
    LawCatalog,
)
from teoria_pipelines.domains.legal_information.laws.parsing import (
    parse_law,
    parse_listing,
    LawValidationError,
)
from teoria_pipelines.schema.pipeline import PipelineSink

ROOT = Path(__file__).parents[4]
BODY = (ROOT / "tests/fixtures/legal_information/law_body.xml").read_bytes()


def version(effective=date(2026, 7, 1), mst="100", name="테스트 법률"):
    return LawVersion(
        "1",
        mst,
        effective,
        name,
        date(2026, 1, 1),
        "999",
        "일부개정",
        {"현행연혁코드": "현행", "법령ID": "000001"},
    )


def listing(rows, total=None, page=1):
    items = "".join(
        f"<law><법령ID>{v.law_id}</법령ID><법령일련번호>{v.mst}</법령일련번호>"
        f"<법령명한글>{v.name}</법령명한글><시행일자>{v.effective_date:%Y%m%d}</시행일자>"
        "<공포일자>20260101</공포일자><공포번호>999</공포번호></law>"
        for v in rows
    )
    return f"<LawSearch><totalCnt>{len(rows) if total is None else total}</totalCnt><page>{page}</page>{items}</LawSearch>".encode()


def response(raw, query=None, operation="list_law_versions"):
    return LawResponse(
        operation, query or {}, datetime.now(timezone.utc), "text/xml", raw
    )


def test_hierarchy_and_source_locations_preserve_branch_headings_deletion_and_addenda():
    p = parse_law(BODY, version())
    assert [r["kind"] for r in p.provisions] == [
        "heading",
        "article",
        "paragraph",
        "subparagraph",
        "item",
        "paragraph",
        "article",
        "addendum",
    ]
    assert p.provisions[1]["number"] == "24의2"
    assert p.provisions[4]["parent_path"] == p.provisions[3]["path"]
    assert p.provisions[4]["content"] == "첫 번째 목"
    assert p.provisions[6]["content"] == "삭제"
    assert p.attachments[0]["title"] == "테스트 표"
    assert "flSeq=123" in p.attachments[0]["source_xml"]


@pytest.mark.parametrize(
    "bad_version",
    [
        replace(version(), effective_date=date(2026, 1, 1)),
        replace(version(), law_id="2"),
        replace(version(), promulgation_number="1000"),
    ],
)
def test_wrong_slice_or_publication_is_not_a_valid_snapshot(bad_version):
    with pytest.raises(LawValidationError, match="law_version_mismatch"):
        parse_law(BODY, bad_version)


@pytest.mark.parametrize(
    "raw",
    [b"<html>error</html>", b"{}", b'<!DOCTYPE x [<!ENTITY e "bad">]><LawSearch/>'],
)
def test_html_empty_envelope_and_entities_are_not_empty_success(raw):
    with pytest.raises(LawValidationError):
        parse_listing(raw)


def test_redaction_removes_raw_and_url_encoded_credential_echoes():
    raw = b"<link>?OC=private%2Bvalue&amp;MST=100</link><echo>private+value</echo>"
    result = redact_xml(raw, "private+value")
    assert b"private" not in result
    assert b"MST=100" in result
    assert redact_xml(result, "private+value") == result


@pytest.mark.asyncio
async def test_catalog_collects_all_pages_and_keeps_same_mst_different_effective_dates():
    client = MolegLawClient(None, path=Path("unused"), executor=None, page_size=1)
    client.request = AsyncMock(
        side_effect=[
            response(listing([version()], 2, 1)),
            response(listing([version(date(2027, 1, 1))], 2, 2)),
        ]
    )
    catalog = await client.collect_catalog("1")
    assert len(catalog.versions) == 2
    assert client.request.call_args.args[1]["page"] == 2
    assert client.request.call_args.args[1]["LID"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pages",
    [
        [listing([version()], 2, 1), listing([version()], 2, 2)],
        [listing([version()], 2, 1), listing([], 2, 2)],
        [listing([version()], 2, 1), listing([version(date(2027, 1, 1))], 3, 2)],
        [listing([replace(version(), law_id="2")], 1, 1)],
    ],
)
async def test_duplicate_missing_changed_total_or_ignored_id_filter_fails(pages):
    client = MolegLawClient(None, path=Path("unused"), executor=None, page_size=1)
    client.request = AsyncMock(side_effect=[response(raw) for raw in pages])
    with pytest.raises(LawValidationError):
        await client.collect_catalog("1")


@pytest.mark.asyncio
async def test_resolution_uses_exact_name_and_rejects_ambiguous_law_ids():
    client = MolegLawClient(None, path=Path("unused"), executor=None)
    client.request = AsyncMock(
        return_value=response(listing([version(name="테스트 법률 시행령"), version()]))
    )
    assert (await client.resolve_target(LawTarget(id="test_law", name="테스트 법률")))[
        0
    ] == "1"
    client.request = AsyncMock(
        return_value=response(listing([version(), replace(version(), law_id="2")]))
    )
    with pytest.raises(LawValidationError, match="unique_exact_match"):
        await client.resolve_target(LawTarget(id="test_law", name="테스트 법률"))


@pytest.mark.asyncio
async def test_date_lookup_never_falls_back_to_current_or_publication_only():
    client = MolegLawClient(None, path=Path("unused"), executor=None)
    client.request = AsyncMock(
        side_effect=LawValidationError("law_provider_contract_failed")
    )
    with pytest.raises(LawValidationError):
        await client.fetch_version(version())
    client.request.assert_awaited_once_with(
        "get_law_version", {"MST": "100", "efYd": "20260701"}
    )


def test_data_only_sink_does_not_require_a_runtime_source():
    sink = PipelineSink(
        type="data_database", schema_name="legal_information", relations=["law"]
    )
    assert sink.source is None
    with pytest.raises(ValidationError):
        PipelineSink(type="data_database", source="invented", relations=["law"])
    with pytest.raises(ValidationError):
        PipelineSink(relations=["law"])


@pytest.mark.asyncio
async def test_partial_law_failure_keeps_checkpoint_and_continues_other_versions(
    monkeypatch,
):
    from teoria_pipelines.domains.legal_information.laws import flows

    t = LawTarget(id="test_law", name="테스트 법률")
    v = version()
    v2 = replace(v, effective_date=date(2027, 1, 1))
    monkeypatch.setattr(flows, "load_targets", Mock(return_value=[t]))
    for name in [
        "start_pipeline_run",
        "start_law_run",
        "record_law_progress",
        "complete_pipeline_run",
        "fail_pipeline_run",
        "update_checkpoint",
    ]:
        monkeypatch.setattr(flows, name, AsyncMock())
    monkeypatch.setattr(flows, "resolve_law_target", AsyncMock(return_value=("1", [])))
    monkeypatch.setattr(
        flows,
        "collect_law_catalog",
        AsyncMock(return_value=LawCatalog("1", [v, v2], [])),
    )
    monkeypatch.setattr(flows, "select_law_versions", AsyncMock(return_value=[v, v2]))
    monkeypatch.setattr(
        flows,
        "fetch_law_version",
        AsyncMock(return_value=response(BODY, operation="get_law_version")),
    )
    monkeypatch.setattr(flows, "save_law_raw", AsyncMock(return_value=["hash"]))
    monkeypatch.setattr(flows, "normalize_law", Mock(return_value=parse_law(BODY, v)))
    monkeypatch.setattr(
        flows,
        "load_law_snapshot",
        AsyncMock(side_effect=[RuntimeError("db error"), uuid4()]),
    )
    with pytest.raises(LawValidationError, match="law_collection_incomplete"):
        await flows.sync_moleg_laws.fn(pipeline_root=str(ROOT))
    assert flows.load_law_snapshot.call_count == 2
    flows.update_checkpoint.assert_not_called()
    flows.complete_pipeline_run.assert_not_called()
    flows.fail_pipeline_run.assert_called_once()


def test_citation_numbers_normalize_zero_padding_and_unknown_article_marker_fails():
    raw = BODY.replace(
        "<조문번호>24</조문번호>".encode(), "<조문번호>024</조문번호>".encode()
    )
    raw = raw.replace(
        "<조문가지번호>2</조문가지번호>".encode(),
        "<조문가지번호>02</조문가지번호>".encode(),
    )
    assert parse_law(raw, version()).provisions[1]["number"] == "24의2"
    with pytest.raises(LawValidationError, match="unknown_article_marker"):
        parse_law(
            BODY.replace(
                "<조문여부>조문</조문여부>".encode(),
                "<조문여부>unknown</조문여부>".encode(),
            ),
            version(),
        )
