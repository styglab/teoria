"""General reproductions of failures found in newly downloaded bid documents."""

import pytest

from teoria_docparse import ParseOptions, parse
from teoria_docparse.compare import block_text, normalized_text, tables_in_order

from .test_parsing import zip_document
from .test_pdf_geometry import clipped_text, pdf, ruled_grid
from .test_pdf_upgrade import multipage_pdf


def workbook(sheet):
    return zip_document(
        {
            "xl/workbook.xml": '<workbook xmlns:r="rels"><sheets><sheet name="Costs" r:id="r1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/worksheets/sheet1.xml": sheet,
        }
    )


def test_formatting_only_cells_do_not_exhaust_retained_worksheet_nodes():
    empty = "".join(f'<c r="B{row}" s="1"/>' for row in range(1, 1001))
    sheet = (
        '<worksheet><sheetData><row><c r="A1" t="inlineStr"><is><t>Cable</t></is></c>'
        + empty
        + '<c r="D1"><v>1200</v></c></row></sheetData><mergeCells><mergeCell ref="A1:C1"/></mergeCells></worksheet>'
    )
    result = parse(workbook(sheet), ParseOptions(max_xml_nodes=20, max_cells=4))
    assert result.success, result.warnings
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (1, 2)
    assert [(cell.text, cell.source.anchor) for cell in table.cells[0]] == [("Cable", "A1"), ("1200", "D1")]


def test_worksheet_content_still_obeys_the_node_budget():
    cells = "".join(f'<c r="A{row}"><v>{row}</v></c>' for row in range(1, 30))
    result = parse(
        workbook(f"<worksheet><sheetData><row>{cells}</row></sheetData></worksheet>"),
        ParseOptions(max_xml_nodes=20),
    )
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_streamed_worksheet_keeps_uncached_formula_and_rejects_entities():
    result = parse(
        workbook('<worksheet><sheetData><row><c r="A1"><f>SUM(B1:B9)</f></c></row></sheetData></worksheet>')
    )
    assert result.success
    assert result.blocks[1].table.cells[0][0].text == "=SUM(B1:B9)"
    assert [w.code for w in result.warnings] == ["FORMULA_NO_CACHE"]
    malicious = '<!DOCTYPE worksheet [<!ENTITY content "expanded">]><worksheet><sheetData><row><c r="A1"><v>&content;</v></c></row></sheetData></worksheet>'
    result = parse(workbook(malicious))
    assert not result.success and result.error_code == "INVALID_FILE"


def test_word_clipping_inside_a_header_cell_does_not_make_a_nested_table(backend):
    stream = ruled_grid()
    stream += clipped_text(60, 150, 15, 50, "1") + clipped_text(75, 150, 40, 50, "booth")
    stream += clipped_text(140, 150, 100, 50, "Quantity")
    stream += clipped_text(40, 100, 100, 50, "Desk") + clipped_text(140, 100, 100, 50, "3")
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1 and (tables[0]["rows"], tables[0]["cols"]) == (2, 2)
    assert normalized_text(tables[0]["cells"][0][0]["text"]) == "1booth"


def test_shading_label_guess_does_not_duplicate_a_larger_ruled_form(backend):
    stream = b"40 70 200 160 re S 40 190 m 240 190 l S 40 150 m 240 150 l S 40 110 m 240 110 l S\n"
    stream += b"80 110 m 80 230 l S 160 70 m 160 230 l S\n"
    for y, label in [(190, "Name"), (150, "Address"), (110, "Agent")]:
        stream += f"0.8 g 160 {y} 80 40 re f 0 g\n".encode()
        stream += f"BT /F1 10 Tf 90 {y + 15} Td ({label}) Tj ET\n".encode()
        stream += f"BT /F1 10 Tf 170 {y + 15} Td (Value) Tj ET\n".encode()
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1 and tables[0]["rows"] == 4
    text = normalized_text(block_text(result.to_dict()["blocks"]))
    assert text.count("Name") == text.count("Address") == text.count("Agent") == 1


@pytest.mark.parametrize("internal_rule", [False, True])
def test_header_fields_combine_unruled_value_fragments_but_keep_real_columns(backend, internal_rule):
    stream = b"40 100 200 90 re S 100 100 m 100 190 l S 40 130 m 240 130 l S 40 160 m 240 160 l S\n"
    if internal_rule:
        stream += b"180 100 m 180 160 l S\n"
    for x, y, width, text in [
        (40, 160, 60, "Field"),
        (100, 160, 140, "Value"),
        (40, 130, 60, "Cost"),
        (100, 130, 80, "1200"),
        (180, 130, 60, "USD"),
        (40, 100, 60, "Term"),
        (100, 100, 80, "10"),
        (180, 100, 60, "months"),
    ]:
        stream += clipped_text(x, y, width, 30, text)
    result = parse(pdf(stream), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1
    assert (tables[0]["rows"], tables[0]["cols"]) == (3, 3 if internal_rule else 2)
    if not internal_rule:
        assert tables[0]["cells"][1][1]["text"] == "1200 USD"
        assert len(tables[0]["cells"][1][1]["blocks"]) == 2
        assert tables[0]["cells"][2][1]["text"] == "10 months"


def numbered_table(y, numbers, row_height=20, second_label="Document", divider=130):
    height = row_height * (len(numbers) + 1)
    stream = f"40 {y} 200 {height} re S {divider} {y} m {divider} {y + height} l S\n".encode()
    for row in range(1, len(numbers) + 1):
        line_y = y + row * row_height
        stream += f"40 {line_y} m 240 {line_y} l S\n".encode()
    for row, (left, right) in enumerate([("ID", second_label)] + [(str(n), f"Item {n}") for n in numbers]):
        bottom = y + height - (row + 1) * row_height
        stream += clipped_text(40, bottom, divider - 40, row_height, left)
        stream += clipped_text(divider, bottom, 240 - divider, row_height, right)
    return stream


@pytest.fixture(params=["pymupdf"])
def backend(request):
    if request.param == "pymupdf":
        pytest.importorskip("pymupdf")
    return ParseOptions(pdf_backend=request.param)


def test_numbered_table_repeated_header_merges_with_both_page_sources(backend):
    result = parse(multipage_pdf([numbered_table(15, [8, 9]), numbered_table(220, [10, 11])]), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1 and (tables[0]["rows"], tables[0]["cols"]) == (5, 2)
    assert [row[0]["text"] for row in tables[0]["cells"]] == ["ID", "8", "9", "10", "11"]
    assert [region["page"] for region in tables[0]["regions"]] == [1, 2]
    assert tables[0]["cells"][3][0]["source"]["page"] == 2
    assert normalized_text(block_text(result.to_dict()["blocks"])).count("Document") == 1
    assert "REPEATED_TABLE_HEADER_MERGED" in {w.code for w in result.warnings}


def test_repeated_headers_can_continue_across_three_pages(backend):
    streams = [
        numbered_table(15, [8, 9]),
        numbered_table(15, [10, 11], row_height=90),
        numbered_table(220, [12, 13]),
    ]
    result = parse(multipage_pdf(streams), backend)
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1 and tables[0]["rows"] == 7
    assert [r["page"] for r in tables[0]["regions"]] == [1, 2, 3]


@pytest.mark.parametrize("change", ["restart", "header", "columns", "body"])
def test_independent_tables_are_not_joined_by_header_similarity(backend, change):
    second = numbered_table(
        220,
        [1, 2] if change == "restart" else [10, 11],
        second_label="Other" if change == "header" else "Document",
        divider=145 if change == "columns" else 130,
    )
    if change == "body":
        second += b"BT /F1 12 Tf 40 290 Td (New section) Tj ET\n"
    result = parse(multipage_pdf([numbered_table(15, [8, 9]), second]), backend)
    assert len(tables_in_order(result.to_dict()["blocks"])) == 2
    assert "REPEATED_TABLE_HEADER_MERGED" not in {w.code for w in result.warnings}
