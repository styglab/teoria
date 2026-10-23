"""Exercise source-shaped failures without including private procurement files."""

import pytest

from kory_parser import ParseOptions, parse
from kory_parser.compare import block_text, normalized_text, tables_in_order

from .test_pdf_geometry import clipped_text, pdf, ruled_grid


@pytest.fixture(params=["pymupdf"])
def backend(request):
    if request.param == "pymupdf":
        pytest.importorskip("pymupdf")
    return ParseOptions(pdf_backend=request.param)


def test_gradient_banner_is_a_heading_without_fragmented_fake_columns(backend):
    stream = b""
    for n in range(40):
        x = 40 + n * 5
        stream += f"0.2 0.5 {n / 40} rg {x} 220 5 40 re f\n".encode()
        stream += f"q {x} 220 5 40 re W n Q\n".encode()
    stream += b"0 0 0 rg BT /F1 22 Tf 55 235 Td (Overview) Tj ET\n"
    for y in [190, 170, 150]:
        stream += f"BT /F1 10 Tf 40 {y} Td (Ordinary body text with specifications.) Tj ET\n".encode()
    result = parse(pdf(stream), backend)
    assert result.success
    assert not tables_in_order(result.to_dict()["blocks"])
    title = next(b for b in result.blocks if b.type == "heading")
    assert title.text == "Overview" and title.level == 1
    assert normalized_text(block_text(result.to_dict()["blocks"])).count("Overview") == 1


def test_narrow_ruled_entry_boxes_remain_a_real_table(backend):
    stream = b"40 200 180 30 re S\n"
    for n in range(1, 12):
        stream += f"{40 + n * 15} 200 m {40 + n * 15} 230 l S\n".encode()
    for n in range(12):
        stream += clipped_text(40 + n * 15, 200, 15, 30, str(n % 10))
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1
    assert (tables[0]["rows"], tables[0]["cols"]) == (1, 12)


def test_heading_style_survives_unframing_of_an_invisible_clip_grid(backend):
    stream = b"q 40 220 100 40 re W n BT /F1 22 Tf 45 235 Td (Title) Tj ET Q\n"
    stream += b"q 140 220 100 40 re W n Q\n"
    for y in [190, 170, 150]:
        stream += f"BT /F1 10 Tf 40 {y} Td (Ordinary specifications remain body text.) Tj ET\n".encode()
    result = parse(pdf(stream), backend)
    assert not tables_in_order(result.to_dict()["blocks"])
    assert any(b.type == "heading" and b.text == "Title" for b in result.blocks)


def test_clipped_header_is_not_an_extra_table_beside_the_complete_grid(backend):
    stream = ruled_grid()
    stream += clipped_text(40, 150, 100, 50, "CPU")
    stream += clipped_text(140, 150, 100, 50, "Qty")
    stream += b"BT /F1 10 Tf 45 125 Td (Server) Tj ET BT /F1 10 Tf 145 125 Td (2) Tj ET\n"
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 2)]
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "CPUQtyServer2"


def test_boundary_text_clip_inside_a_real_cell_is_not_a_nested_table(backend):
    stream = b"40 25 180 150 re S 40 145 m 220 145 l S\n"
    stream += clipped_text(40, 145, 180, 30, "Description")
    stream += b"BT /F1 10 Tf 50 110 Td (Before) Tj ET\n"
    stream += clipped_text(60, 40, 160, 15, "Part of the paragraph")
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 1)]
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "DescriptionBeforePartoftheparagraph"


def test_dates_quantities_and_field_values_do_not_become_headings(backend):
    stream = b"BT /F1 22 Tf 40 270 Td (Specifications) Tj ET\n"
    stream += b"BT /F1 18 Tf 40 230 Td (2026. 10. 20.) Tj ET\n"
    stream += b"BT /F1 18 Tf 40 200 Td (128GB DDR5-5600) Tj ET\n"
    stream += b"BT /F1 18 Tf 40 170 Td (CPU: 32 cores) Tj ET\n"
    for y in [140, 120, 100]:
        stream += f"BT /F1 10 Tf 40 {y} Td (Ordinary specifications remain body text.) Tj ET\n".encode()
    result = parse(pdf(stream), backend)
    assert [(b.text, b.level) for b in result.blocks if b.type == "heading"] == [("Specifications", 1)]


def test_heading_detection_does_not_promote_a_repeated_running_header(backend):
    from .test_pdf_upgrade import multipage_pdf

    streams = []
    for _ in range(2):
        stream = b"BT /F1 18 Tf 40 285 Td (Running title) Tj ET\n"
        stream += (
            b"BT /F1 10 Tf 40 150 Td (The ordinary body describes the server and its specifications.) Tj ET\n"
        )
        streams.append(stream)
    result = parse(multipage_pdf(streams), backend)
    assert not any(b.type == "heading" and b.text == "Running title" for b in result.blocks)


def test_three_page_numbered_continuation_keeps_all_source_pages(backend):
    from .test_pdf_upgrade import multipage_pdf

    streams = []
    for number, (y, height) in enumerate([(15, 45), (15, 265), (240, 40)], 1):
        streams.append(
            f"40 {y} 200 {height} re S\n".encode() + clipped_text(40, y, 200, height, f"{number}. Item")
        )
    result = parse(multipage_pdf(streams), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1 and tables[0]["rows"] == 3
    assert [ref["page"] for ref in tables[0]["regions"]] == [1, 2, 3]
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "1.Item2.Item3.Item"


def test_lettered_page_continuation_retains_a_full_width_cell_and_source_regions(backend):
    from .test_pdf_upgrade import multipage_pdf

    first = b"40 25 200 100 re S 40 100 m 240 100 l S 140 100 m 140 125 l S\n"
    first += clipped_text(40, 100, 100, 25, "Item")
    first += clipped_text(140, 100, 100, 25, "Qty")
    first += clipped_text(40, 25, 200, 75, "a. CPU")
    second = b"40 220 200 60 re S\n" + clipped_text(40, 220, 200, 60, "b. GPU")
    result = parse(multipage_pdf([first, second]), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1
    table = tables[0]
    assert (table["rows"], table["cols"]) == (2, 2)
    assert table["cells"][1][0]["col_span"] == 2
    assert normalized_text(table["cells"][1][0]["text"]) == "a.CPUb.GPU"
    assert [ref["page"] for ref in table["regions"]] == [1, 2]


def test_korean_list_continuation_requires_the_next_marker():
    from kory_parser.pdf_continuation import numbered_continuation

    assert numbered_continuation("가. setup\n나. drivers", "다. accounts")
    assert not numbered_continuation("가. setup\n나. drivers", "가. a new form")
    assert not numbered_continuation("a. CPU", "다. a different list")
