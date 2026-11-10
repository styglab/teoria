"""Topic-independent reading order, paragraph boundaries and structural hierarchy."""

from collections import Counter
from dataclasses import replace

import pymupdf
import pytest

from kory_parser import parse
from kory_parser.models import Block, SourceRef
from kory_parser.pdf_paragraphs import list_levels, marker, recover_paragraphs
from kory_parser.pdf_reading import reading_order
from kory_parser.pdf_typography import LineStyle, PdfTypography
from kory_parser.pdf_words import extract_text


def block(text, box, kind="paragraph", page=1):
    return Block(
        kind, text, source=SourceRef("pdf", page=page, bbox=box, coordinate_system="top_left", unit="pt")
    )


def test_two_columns_read_to_the_bottom_before_the_next_column():
    left = [block(f"Left row {i}", (30, 100 + i * 15, 250, 110 + i * 15)) for i in range(5)]
    right = [block(f"Right row {i}", (330, 100 + i * 15, 550, 110 + i * 15)) for i in range(5)]
    title = block("Full width heading", (30, 30, 550, 50), "heading")
    result = reading_order([title, *sum(zip(left, right), ())], {1: (600, 800)})
    assert result == [title, *left, *right]


def test_three_columns_and_full_width_table_split_reading_bands():
    bands = []
    for top in (70, 300):
        columns = [
            [
                block(
                    f"Band {top} column {col} row {row}",
                    (30 + col * 290, top + row * 15, 260 + col * 290, top + row * 15 + 10),
                )
                for row in range(4)
            ]
            for col in range(3)
        ]
        bands.append(columns)
    table = block("", (30, 180, 840, 240), "table")
    source = [*sum(zip(*bands[0]), ()), table, *sum(zip(*bands[1]), ())]
    result = reading_order(source, {1: (900, 700)})
    assert result == [
        *[b for column in bands[0] for b in column],
        table,
        *[b for column in bands[1] for b in column],
    ]
    assert Counter(map(id, result)) == Counter(map(id, source))


def test_short_aligned_fields_are_not_enough_evidence_for_columns():
    fields = [block(str(i), (x, 100 + i * 20, x + 15, 110 + i * 20)) for i in range(4) for x in (30, 300)]
    assert reading_order(fields, {1: (600, 800)}) == fields


def test_pdf_does_not_fuse_words_from_aligned_columns():
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=500)
        for i in range(8):
            page.insert_text((30, 100 + 16 * i), f"Left column line {i} has ordinary words.", fontsize=10)
            page.insert_text((330, 100 + 16 * i), f"Right column line {i} has ordinary words.", fontsize=10)
        data = doc.tobytes()
    result = parse(data)
    assert result.success
    assert not any("Left column" in b.text and "Right column" in b.text for b in result.blocks)
    text = result.markdown
    assert text.index("Left column line 7") < text.index("Right column line 0")


def styled_lines(specifications):
    typography = PdfTypography()
    blocks = []
    for text, box, native_block, font in specifications:
        b = block(text, box)
        typography.styles[(1, box, text)] = LineStyle(10, 0, native_block, font)
        blocks.append(b)
    return blocks, typography


def test_paragraph_reconstruction_keeps_each_original_line_region():
    blocks, typography = styled_lines(
        [
            ("First physical line", (30, 100, 250, 112), 1, "Body"),
            ("continues on another line.", (30, 114, 240, 126), 1, "Body"),
            ("A separate paragraph.", (30, 160, 220, 172), 2, "Body"),
        ]
    )
    result = recover_paragraphs(blocks, typography)
    assert [b.text for b in result] == [
        "First physical line continues on another line.",
        "A separate paragraph.",
    ]
    assert result[0].regions == [b.source for b in blocks[:2]]
    assert result[0].source.bbox == (30, 100, 250, 126)
    assert blocks[0].text == "First physical line"


def test_indented_single_line_paragraph_does_not_absorb_the_next_paragraph():
    blocks, typography = styled_lines(
        [
            ("An indented short paragraph.", (45, 100, 240, 112), 1, "Body"),
            ("The next paragraph starts here", (45, 114, 250, 126), 1, "Body"),
            ("and continues across several", (30, 128, 250, 140), 1, "Body"),
            ("measured lines in the document", (30, 142, 250, 154), 1, "Body"),
            ("before it finally ends.", (30, 156, 190, 168), 1, "Body"),
        ]
    )
    result = recover_paragraphs(blocks, typography)
    assert len(result) == 2
    assert result[0].text == blocks[0].text
    assert len(result[1].regions) == 4


@pytest.mark.parametrize("barrier", ["heading", "table", "image"])
def test_paragraphs_do_not_merge_across_structural_elements(barrier):
    blocks, typography = styled_lines(
        [("Before", (30, 100, 250, 112), 1, "Body"), ("After", (30, 114, 250, 126), 1, "Body")]
    )
    blocks.insert(1, block("Barrier", (30, 112, 250, 114), barrier))
    assert len(recover_paragraphs(blocks, typography)) == 3


def test_code_lines_and_separate_pages_keep_their_boundaries():
    blocks, typography = styled_lines(
        [
            ("if value:", (30, 100, 250, 112), 1, "Courier"),
            ("    return value", (30, 114, 250, 126), 1, "Courier"),
        ]
    )
    assert len(recover_paragraphs(blocks, typography)) == 2
    blocks[1] = replace(blocks[1], source=replace(blocks[1].source, page=2))
    assert len(recover_paragraphs(blocks, typography)) == 2


def test_lists_keep_nested_indent_and_reset_at_a_column_transition():
    source = [
        block("1. Outer", (30, 100, 230, 112)),
        block("a. Nested", (48, 115, 230, 127)),
        block("2. Outer", (30, 130, 230, 142)),
        block("3. Next column", (330, 40, 530, 52)),
    ]
    result = list_levels(source)
    assert [b.level for b in result] == [1, 2, 1, 1]
    assert all(b.type == "list" for b in result)


@pytest.mark.parametrize("text", ["* = required field", "* Name: __________", "- 12.5", "1.25 is a decimal"])
def test_form_fields_and_numeric_values_are_not_list_markers(text):
    assert marker(text) is None


def test_pdf_recovers_three_numbered_heading_levels():
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=600)
        for y, title, size in (
            (60, "1 Overview", 15),
            (110, "1.1 Details", 12),
            (160, "1.1.1 Specifics", 10),
        ):
            page.insert_text((30, y), title, fontsize=size, fontname="hebo")
        for i in range(8):
            page.insert_text(
                (30, 220 + 16 * i), "Ordinary body text keeps the document font baseline.", fontsize=10
            )
        data = doc.tobytes()
    result = parse(data)
    actual = {b.text: b.level for b in result.blocks if b.type == "heading"}
    assert actual["1 Overview"] == 1
    assert actual["1.1 Details"] == 2
    assert actual["1.1.1 Specifics"] == 3


def test_empty_regions_do_not_change_existing_serialized_blocks():
    from kory_parser.models import ParseResult

    result = ParseResult(True, "pdf", blocks=[block("Single line", (30, 30, 100, 40))])
    assert "regions" not in result.to_dict()["blocks"][0]
    result.blocks[0].regions = [result.blocks[0].source]
    assert result.to_dict()["blocks"][0]["regions"][0]["page"] == 1


def test_expanded_ligature_characters_with_equal_origins_keep_source_order():
    from .test_pdf_text_optimization import char

    chars = [char("f", 10, 20), char("i", 10, 20), char("l", 15, 20), char("e", 20, 20), char("s", 25, 20)]
    chars[1]["x1"] = 12
    assert extract_text(chars) == "files"


def test_multiline_title_and_rotated_margin_text_are_not_confused():
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=600)
        page.insert_text(
            (130, 50), "A Generic Title:\nThe Second Line", fontsize=18, fontname="hebo", lineheight=1.2
        )
        page.insert_text((20, 300), "Rotated margin", fontsize=18, rotate=90)
        for i in range(8):
            page.insert_text(
                (50, 160 + 14 * i), "Regular body text is measured in its own document context.", fontsize=10
            )
        data = doc.tobytes()
    result = parse(data)
    assert "Rotated margin" in result.markdown
    assert not any(b.type == "heading" and "Rotated" in b.text for b in result.blocks)
    title = next(b for b in result.blocks if b.type == "heading")
    assert title.text == "A Generic Title: The Second Line"
    assert len(title.regions) == 2
