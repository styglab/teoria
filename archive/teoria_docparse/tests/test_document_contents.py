"""Contents extraction must preserve native evidence and avoid changing prose/tables."""

import copy

from teoria_docparse import Block, Cell, ParseOptions, ParseResult, SourceRef, Table, parse
from teoria_docparse.document_contents import recover_contents
from teoria_docparse.models import has_contents_title

from .test_pdf_geometry import pdf


def line(text, y, page=1, x=20, kind="paragraph"):
    return Block(
        kind,
        text,
        source=SourceRef("pdf", page=page, bbox=(x, y, 550, y + 12), coordinate_system="top_left", unit="pt"),
    )


def test_numbered_contents_are_separate_from_unchanged_text_and_tables():
    blocks = [
        line("Contents", 20),
        line("1 First chapter .... 3", 50),
        line("1.1 Child heading .... 4", 70),
        line("2 Second chapter .... 6", 90),
        line("1 First chapter", 50, page=3),
        line("1.1 Child heading", 50, page=4),
    ]
    before = copy.deepcopy(blocks)
    contents = recover_contents(blocks)
    assert blocks == before
    entries = contents[0].entries
    assert [(e.title, e.level, e.printed_page_label) for e in entries] == [
        ("First chapter", 1, "3"),
        ("Child heading", 2, "4"),
        ("Second chapter", 1, "6"),
    ]
    assert entries[1].parent_id == entries[0].entry_id
    assert entries[0].target.page == 3
    assert entries[2].target is None


def test_korean_section_marker_and_body_title_can_have_separate_regions():
    blocks = [
        line("목 차", 20),
        line("Ⅰ. 일반사항 .... 3", 50),
        line("Ⅱ. 특수조건 .... 5", 70),
        line("Ⅰ", 50, page=3, x=20, kind="heading"),
        line("일반사항", 50, page=3, x=70, kind="heading"),
    ]
    entry = recover_contents(blocks)[0].entries[0]
    assert entry.target_status == "resolved"
    assert entry.target.bbox == (20, 50, 550, 62)
    assert entry.target.page == 3


def test_same_subheading_under_different_chapters_does_not_end_contents():
    blocks = [
        line("목차", 20),
        line("제1장 공통 조건", 50),
        line("1. 적용범위 .... 3", 70),
        line("제2장 설치 조건", 90),
        line("1. 적용범위 .... 5", 110),
        line("제3장 시험 조건", 130),
        line("1. 적용범위 .... 7", 150),
    ]
    entries = recover_contents(blocks)[0].entries
    assert len(entries) == 6
    assert len({e.parent_id for e in entries if e.number == "1."}) == 3


def test_appendix_letters_do_not_shift_decimal_chapter_depth():
    blocks = [
        line("Contents", 20),
        line("1 Main chapter .... 1", 50),
        line("1.1 Child chapter .... 2", 70),
        line("C Appendix .... 20", 90),
        line("D License .... 21", 110),
    ]
    assert [e.level for e in recover_contents(blocks)[0].entries] == [1, 2, 1, 1]


def test_roman_chapters_have_letter_children_including_c_and_d():
    blocks = [
        line("Contents", 20),
        line("I. Introduction .... 4", 50),
        line("A. Preparation .... 5", 70),
        line("B. Method .... 6", 90),
        line("C. Result .... 7", 110),
        line("D. Discussion .... 8", 130),
    ]
    assert [e.level for e in recover_contents(blocks)[0].entries] == [1, 2, 2, 2, 2]


def test_wrapped_entry_keeps_both_physical_regions():
    blocks = [
        line("Contents", 20),
        line("1 An unusually long", 50),
        line("chapter title .... 3", 65, x=35),
        line("2 Another chapter .... 4", 90),
    ]
    entries = recover_contents(blocks)[0].entries
    assert entries[0].title == "An unusually long chapter title"
    assert entries[0].printed_page_label == "3"
    assert len(entries[0].regions) == 2
    assert len(entries) == 2


def test_table_row_connects_number_title_and_page_without_cell_mutation():
    ref = SourceRef("word/document.xml", "table[1]/cell[0,0]")
    cells = [
        [Cell("I.", source=ref), Cell("Introduction ........", source=ref), Cell("4", source=ref)],
        [Cell("II.", source=ref), Cell("Method ........", source=ref), Cell("5", source=ref)],
    ]
    blocks = [Block("paragraph", "TABLE OF CONTENTS", source=ref), Block("table", table=Table(2, 3, cells))]
    before = copy.deepcopy(blocks)
    entries = recover_contents(blocks)[0].entries
    assert [(e.title, e.printed_page_label) for e in entries] == [("Introduction", "4"), ("Method", "5")]
    assert entries[0].source == ref
    assert blocks == before


def test_mention_in_submission_instructions_is_not_a_contents_header():
    assert not has_contents_title([line("목차/평가조견표를 제출해야 합니다", 20)])
    assert (
        recover_contents(
            [
                line("목차/평가조견표를 제출해야 합니다", 20),
                line("1. First .... 3", 50),
                line("2. Second .... 4", 70),
            ]
        )
        == []
    )
    assert "contents" not in ParseResult(True, "pdf").to_dict()


def test_fast_guard_finds_a_contents_title_in_a_nested_native_cell():
    blocks = [Block("table", table=Table(1, 1, [[Cell("< 목  차 >")]]))]
    assert has_contents_title(blocks)


def test_new_option_preserves_existing_positional_option_arguments():
    options = ParseOptions("pymupdf", False, False, False)
    assert options.keep_empty_paragraphs is False
    assert options.extract_contents is False


def test_experimental_contents_is_explicit_and_preserves_default_document_output():
    document = pdf(
        b"BT /F1 12 Tf 40 160 Td (Contents) Tj 0 -25 Td (1. Intro..........3) Tj 0 -20 Td (2. Method..........4) Tj ET"
    )
    default = parse(document).to_dict()
    enabled = parse(document, ParseOptions(extract_contents=True)).to_dict()
    assert "contents" not in default
    contents = enabled.pop("contents")
    assert [e["title"] for e in contents[0]["entries"]] == ["Intro", "Method"]
    assert enabled == default


def test_printed_page_labels_do_not_guess_a_physical_target():
    entries = recover_contents(
        [
            line("Contents", 20),
            line("1 Missing chapter .... 3", 50),
            line("2 Another missing chapter .... 4", 70),
        ]
    )[0].entries
    assert all(e.target is None and e.target_status == "unresolved" for e in entries)


def test_repeated_body_titles_remain_ambiguous():
    blocks = [
        line("Contents", 20),
        line("1 Same title .... 3", 50),
        line("2 Other title .... 4", 70),
        line("1 Same title", 50, page=3),
        line("1 Same title", 50, page=8),
    ]
    entry = recover_contents(blocks)[0].entries[0]
    assert entry.target_status == "ambiguous"
    assert entry.target is None


def test_repeated_running_header_does_not_end_a_multipage_contents():
    blocks = [
        line("Manual 2026", 10),
        line("Contents", 100),
        line("1 Main .... 3", 130),
        line("Manual 2026", 10, page=2),
        line("1.1 Child .... 4", 100, page=2),
        line("Manual 2026", 10, page=3),
        line("2 Next .... 5", 100, page=3),
    ]
    entries = recover_contents(blocks, {1: (600, 800), 2: (600, 800), 3: (600, 800)})[0].entries
    assert len(entries) == 3
    assert all("Manual" not in e.title for e in entries)


def test_body_prose_is_not_added_after_a_paged_contents_section():
    blocks = [
        line("목차", 20),
        line("1. 구매 개요 .... 1", 50),
        line("2. 규격 .... 3", 70),
        line("사업 개요", 50, page=2, kind="heading"),
        line("1. 목적", 70, page=2),
        line("본 사업의 목적과 추진 배경을 설명한다.", 90, page=2),
        line("2. 범위", 110, page=2),
        line("사업의 범위는 다음과 같다.", 130, page=2),
    ]
    assert len(recover_contents(blocks)[0].entries) == 2


def test_reference_numbers_in_unpaged_titles_are_not_page_labels():
    blocks = [
        line("Contents", 20),
        line("B.1. Changes from RFC 2818", 50),
        line("B.2. Changes from RFC 7230", 70),
    ]
    entries = recover_contents(blocks, page_labels=set())[0].entries
    assert [e.title for e in entries] == ["Changes from RFC 2818", "Changes from RFC 7230"]
    assert all(e.printed_page_label is None for e in entries)


def test_required_proposal_outline_needs_navigation_evidence():
    blocks = [
        line("[붙임 3] 제안서 작성 서식", 20),
        line("목차", 50),
        line("Ⅰ. 제안개요", 70),
        line("1. 제안 목적 및 배경", 90),
        line("Ⅱ. 사업제안 내용(예시)", 110),
        line("아래의 항목을 참고하여 자유롭게 기술", 130),
    ]
    before = copy.deepcopy(blocks)
    assert recover_contents(blocks) == []
    assert blocks == before


def test_real_proposal_contents_keeps_page_and_body_evidence():
    for paged in (False, True):
        suffix = " .... 3" if paged else ""
        blocks = [
            line("제안서 작성 양식", 20),
            line("목차", 50),
            line("Ⅰ. 제안개요" + suffix, 70),
            line("Ⅱ. 사업제안 내용" + suffix, 90),
        ]
        if not paged:
            blocks += [line("Ⅰ. 제안개요", 50, page=3), line("Ⅱ. 사업제안 내용", 50, page=4)]
        entries = recover_contents(blocks)[0].entries
        assert len(entries) == 2
        assert entries[0].printed_page_label == "3" if paged else entries[0].target_status == "resolved"
