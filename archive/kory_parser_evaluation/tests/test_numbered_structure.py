"""Literal source whitespace, sibling relationships and multiline provenance."""

from dataclasses import asdict
from html import escape

from kory_parser import ParseOptions, parse
from kory_parser.models import Block, Cell, SourceRef, Span, Table
from kory_parser.numbered_structure import recover_numbered_structure

from .document_fixtures import zip_document


def document(lines):
    return zip_document({"Contents/header.xml": "<head/>", "Contents/section0.xml": "<sec>" + "".join(
        f'<p id="{i}"><run><t>{escape(text).replace(chr(10), "<lineBreak/>")}</t></run></p>'
        for i, text in enumerate(lines)
    ) + "</sec>"})


def test_source_indented_outline_has_siblings_and_restarts_without_text_changes():
    lines = ["Ⅰ. Design", "    1. Unit", "      가. Frame", "        1) Width", "        2) Height",
             "      나. Processor", "        1) Cores", "        2) Clock", "Ⅱ. Delivery", "    1. Timing", "    2. Place"]
    data = document(lines)
    before = parse(data, ParseOptions(recover_numbered_structure=False))
    after = parse(data, ParseOptions(recover_numbered_structure=True))
    assert before.success and after.success
    assert [b.type for b in before.blocks] == ["paragraph"] * len(lines)
    assert [b.type for b in after.blocks] == ["list"] * len(lines)
    assert [b.level for b in after.blocks] == [1, 2, 3, 4, 4, 3, 4, 4, 1, 2, 2]
    for old, new in zip(before.blocks, after.blocks):
        a, b = asdict(old), asdict(new)
        for key in ("type", "level"):
            a.pop(key); b.pop(key)
        assert a == b
    assert "      1) Width" in after.markdown
    assert not after.contents


def test_multiline_parent_and_note_preserve_text_and_reference_without_splitting():
    lines = ["Ⅲ. Design", "  1. Unit", "    가. Outer\n      1) Embedded", "      2) Detail\nordinary continuation",
             "    나. Inner", "Ⅳ. Support", "  1. Service"]
    before = parse(document(lines))
    after = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert [b.level for b in after.blocks] == [1, 2, 3, 4, 3, 1, 2]
    assert len(after.blocks) == len(lines)
    assert [b.text for b in after.blocks] == [b.text for b in before.blocks]
    assert [b.source for b in after.blocks] == [b.source for b in before.blocks]


def test_isolated_numbering_flat_numbers_dates_and_versions_are_not_promoted():
    for lines in [["2026. Notice", "1.2 GHz", "1. A", "2. B", "가. X", "나. Y"],
                  ["Ⅰ. One section", "  1. A", "  2. B"],
                  ["Ⅰ. Flat", "1. A", "가. X", "Ⅱ. Flat", "2. B"]]:
        result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
        assert result.success
        assert all(b.type == "paragraph" and b.level is None for b in result.blocks)


def test_source_spans_required_and_native_metadata_and_parts_are_boundaries():
    native = Block("heading", "Native", level=5)
    blocks = [Block("paragraph", "Ⅰ. First", spans=[Span("Ⅰ. First")], source=SourceRef("a")),
              Block("paragraph", "  1. A", spans=[Span("  1. A")], source=SourceRef("a")), native,
              Block("paragraph", "Ⅱ. Second", spans=[Span("Ⅱ. Second")], source=SourceRef("b"))]
    expected = [asdict(b) for b in blocks]
    recover_numbered_structure(blocks)
    assert [asdict(b) for b in blocks] == expected
    blocks = [Block("paragraph", t) for t in ["Ⅰ. First", "  1. A", "Ⅱ. Second"]]
    recover_numbered_structure(blocks)
    assert all(b.type == "paragraph" for b in blocks)


def test_cell_text_is_not_split_and_numbering_context_does_not_cross_cells():
    first = Cell(blocks=[Block("paragraph", "Ⅰ. First", spans=[Span("Ⅰ. First")]),
                         Block("paragraph", "1. A", spans=[Span("  1. A")])])
    second = Cell("plain", blocks=[Block("paragraph", "Ⅱ. Second", spans=[Span("Ⅱ. Second")])])
    flat = Cell("Ⅰ. Flat\n  1. A\nⅡ. Flat")
    block = Block("table", table=Table(1, 3, [[first, second, flat]]))
    expected = asdict(block)
    recover_numbered_structure([block])
    assert asdict(block) == expected


def test_conflicting_marker_families_at_same_source_indent_are_ambiguous():
    lines = ["Ⅰ. Design", "  1. Unit", "    가. Outer", "    1) Same-indent detail", "    나. Inner", "Ⅱ. Support"]
    result = parse(document(lines), ParseOptions(recover_numbered_structure=True))
    assert [b.level for b in result.blocks] == [1, 2, 3, None, 3, 1]
    assert result.blocks[3].type == "paragraph"


def test_leading_tabs_and_spans_split_inside_prefix_are_preserved():
    blocks = [Block("paragraph", "Ⅰ. Design", spans=[Span("Ⅰ"), Span(". Design")]),
              Block("paragraph", "1. Unit", spans=[Span("\t"), Span("1"), Span(". Unit")]),
              Block("paragraph", "가. Component", spans=[Span("\t\t가. Component")]),
              Block("paragraph", "Ⅱ. Support", spans=[Span("Ⅱ. Support")])]
    recover_numbered_structure(blocks)
    assert [b.level for b in blocks] == [1, 2, 3, 1]


def test_explicit_option_does_not_reclassify_other_formats():
    data = zip_document({"word/document.xml": '<document><body>' + ''.join(
        f'<p><r><t>{text}</t></r></p>' for text in ["Ⅰ. Design", "  1. Unit", "Ⅱ. Support"]
    ) + '</body></document>'})
    before = parse(data).to_dict()
    after = parse(data, ParseOptions(recover_numbered_structure=True)).to_dict()
    assert before == after
