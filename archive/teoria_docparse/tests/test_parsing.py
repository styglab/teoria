import io
import struct

import pytest
from PIL import Image

from teoria_docparse import ParseOptions, parse
from teoria_docparse.character_maps import johab
from teoria_docparse.hwp_binary import hwp_text, read_records
from teoria_docparse.models import Cell, ParseError, plain_text, table_from_cells

from .document_fixtures import docx, hwp3, hwp5, hwp_record, hwpx, hwpx_cell, simple_pdf, zip_document


def test_hwpx_current_text_deletion_and_insertion_in_tails():
    result = parse(
        hwpx(
            '<p><run><t>CPU <deleteBegin Id="1"/>old<deleteEnd Id="1"/>'
            '<insertBegin Id="2"/>new<insertEnd Id="2"/> end</t></run></p>'
        )
    )
    assert result.success
    assert plain_text(result.blocks) == "CPU new end"


def test_hwpx_deleted_table_is_excluded_and_current_table_kept():
    table = '<tbl id="t1" rowCnt="1" colCnt="1"><tr>' + hwpx_cell("CPU") + "</tr></tbl>"
    result = parse(
        hwpx(
            '<p><run><t><deleteBegin Id="1"/></t>'
            + table
            + '<t><deleteEnd Id="1"/></t>'
            + table
            + "</run></p>"
        )
    )
    assert result.success
    tables = [b.table for b in result.blocks if b.table]
    assert len(tables) == 1
    assert tables[0].cells[0][0].text == "CPU"


def test_hwpx_merged_and_nested_table_structure():
    inner = '<tbl id="inner" rowCnt="1" colCnt="1"><tr>' + hwpx_cell("RAM") + "</tr></tbl>"
    outer = '<tbl id="outer" rowCnt="2" colCnt="2"><tr>' + hwpx_cell(inner, rs=2) + hwpx_cell("CPU", col=1)
    outer += "</tr><tr>" + hwpx_cell("32", row=1, col=1) + "</tr></tbl>"
    result = parse(hwpx("<p><run>" + outer + "</run></p>"))
    assert result.success
    table = result.blocks[0].table
    assert (table.rows, table.cols) == (2, 2)
    assert table.cells[1][0].covered
    assert table.cells[0][0].blocks[0].table.source_id == "inner"
    assert table.cells[0][1].source.anchor.endswith("/cell[0,1]")
    assert 'rowspan="2"' in result.markdown


def test_docx_vertical_merge_and_deleted_content():
    cell = '<w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>CPU</w:t></w:r></w:p></w:tc>'
    continuation = "<w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>"
    result = parse(
        docx(
            "<w:p><w:del><w:r><w:delText>old</w:delText></w:r></w:del>"
            "<w:ins><w:r><w:t>new</w:t></w:r></w:ins></w:p>"
            "<w:tbl><w:tr>" + cell + "</w:tr><w:tr>" + continuation + "</w:tr></w:tbl>"
        )
    )
    assert result.success
    assert result.blocks[0].text == "new"
    table = result.blocks[1].table
    assert table.cells[0][0].row_span == 2
    assert table.cells[1][0].covered


def test_docx_paragraph_and_table_order():
    p = lambda text: "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>"
    result = parse(
        docx(p("before") + "<w:tbl><w:tr><w:tc>" + p("inside") + "</w:tc></w:tr></w:tbl>" + p("after"))
    )
    assert [b.type for b in result.blocks] == ["paragraph", "table", "paragraph"]
    assert plain_text(result.blocks) == "before\ninside\nafter"


def test_hwp5_native_ole_and_record_body():
    body = hwp_record(0x42, 0, bytes(22)) + hwp_record(0x43, 1, "서버 CPU 32\r".encode("utf-16le"))
    result = parse(hwp5(body))
    assert result.success, result.warnings
    assert result.file_type == "hwp"
    assert result.blocks[0].text == "서버 CPU 32"
    assert result.blocks[0].source.part == "BodyText/Section0"


def test_hwp5_control_byte_consumption():
    data = "A".encode("utf-16le") + struct.pack("<H", 9) + bytes(14) + "B\nC".encode("utf-16le")
    assert hwp_text(data) == "A\tB\nC"
    with pytest.raises(ParseError):
        read_records(struct.pack("<I", (100 << 20) | 0x43))


def test_hwp3_native_stream():
    result = parse(hwp3("CPU 32"))
    assert result.success, result.warnings
    assert result.blocks[0].text == "CPU 32"


def test_johab_hangul_symbols_and_invalid_reserved_index():
    assert johab(0x8861) == "가"
    assert johab(0x8442) == "ㄱ"
    assert johab(0x8860) == "\ufffd"
    assert johab(0x3366) == "□"


def test_hwpml_table():
    data = b'<HWPML><BODY><SECTION><P><TEXT><CHAR>Heading</CHAR><TABLE RowCount="1" ColCount="1"><ROW><CELL RowAddr="0" ColAddr="0" RowSpan="1" ColSpan="1"><PARALIST><P><TEXT><CHAR>CPU</CHAR></TEXT></P></PARALIST></CELL></ROW></TABLE></TEXT></P></SECTION></BODY></HWPML>'
    result = parse(data)
    assert result.success
    assert result.blocks[0].text == "Heading"
    assert result.blocks[1].table.cells[0][0].text == "CPU"


def test_pdf_text_table_and_coordinate_contract():
    result = parse(simple_pdf())
    assert result.success, result.warnings
    assert result.page_count == 1
    assert result.blocks[0].text == "Heading"
    table = next(b for b in result.blocks if b.table)
    assert (table.table.rows, table.table.cols) == (2, 2)
    assert [c.text for row in table.table.cells for c in row] == ["CPU", "32", "RAM", "64"]
    assert table.source.coordinate_system == "top_left"
    assert table.source.unit == "pt"


def test_image_is_not_success_without_ocr():
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format="PNG")
    result = parse(stream.getvalue())
    assert not result.success
    assert result.error_code == "NEEDS_OCR"
    assert result.blocks[0].type == "image"


def test_xlsx_sparse_addresses_merge_and_relationship_order():
    data = zip_document(
        {
            "xl/workbook.xml": '<workbook xmlns:r="rels"><sheets><sheet name="Sheet" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/worksheets/sheet1.xml": '<worksheet><sheetData><row><c r="A1" t="inlineStr"><is><t>CPU</t></is></c><c r="C1"><v>32</v></c></row></sheetData><mergeCells><mergeCell ref="A1:B2"/></mergeCells></worksheet>',
        }
    )
    result = parse(data, ParseOptions(sheet_layout="source"))
    assert result.success, result.warnings
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (2, 3)
    assert (table.cells[0][0].row_span, table.cells[0][0].col_span) == (2, 2)
    assert table.cells[1][1].covered
    assert table.cells[0][2].text == "32"
    compact = parse(data)
    assert (compact.blocks[1].table.rows, compact.blocks[1].table.cols) == (1, 2)
    assert compact.blocks[1].table.cells[0][0].source.anchor == "A1"
    assert compact.blocks[1].table.cells[0][1].source.anchor == "C1"


def test_xls_biff_values_and_merged_cells():
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet("Components")
    sheet.write_merge(0, 1, 0, 0, "CPU")
    sheet.write(0, 1, 32)
    sheet.write(1, 1, 64)
    stream = io.BytesIO()
    book.save(stream)
    result = parse(stream.getvalue())
    assert result.success, result.warnings
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (2, 2)
    assert table.cells[0][0].row_span == 2
    assert table.cells[1][0].covered
    assert table.cells[1][1].text == "64"


def test_encrypted_pdf_exception_is_classified():
    import pymupdf

    with pymupdf.open(stream=simple_pdf(), filetype="pdf") as doc:
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    result = parse(data)
    assert not result.success
    assert result.error_code == "ENCRYPTED"


def test_pdf_empty_grid_is_not_text_success():
    result = parse(
        simple_pdf()
        .replace(b"(Heading)", b"(       )")
        .replace(b"(CPU)", b"(   )")
        .replace(b"(RAM)", b"(   )")
        .replace(b"(32)", b"(  )")
        .replace(b"(64)", b"(  )")
    )
    assert not result.success
    assert result.error_code == "NEEDS_OCR"


def test_hwp5_merged_table_from_binary_cell_addresses():
    body = hwp_record(0x42, 0, bytes(22)) + hwp_record(0x47, 1, b" lbt")
    body += hwp_record(0x4D, 2, struct.pack("<IHH", 0, 2, 2))
    for row, col, rs, value in [(0, 0, 2, "CPU"), (0, 1, 1, "32"), (1, 1, 1, "64")]:
        cell = bytes(8) + struct.pack("<HHHH", col, row, 1, rs)
        body += hwp_record(0x48, 2, cell)
        body += hwp_record(0x42, 3, bytes(22))
        body += hwp_record(0x43, 4, (value + "\r").encode("utf-16le"))
    result = parse(hwp5(body))
    assert result.success, result.warnings
    table = result.blocks[0].table
    assert (table.rows, table.cols) == (2, 2)
    assert table.cells[0][0].row_span == 2
    assert table.cells[1][0].covered
    assert table.cells[1][1].text == "64"


def test_pptx_follows_relationship_order_and_skips_hidden():
    data = zip_document(
        {
            "ppt/presentation.xml": '<presentation xmlns:r="rels"><sldIdLst><sldId id="1" r:id="second"/><sldId id="2" r:id="first"/></sldIdLst></presentation>',
            "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="first" Target="slides/slide1.xml"/><Relationship Id="second" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": '<sld show="0"><spTree><sp><p><r><t>hidden</t></r></p></sp></spTree></sld>',
            "ppt/slides/slide2.xml": "<sld><spTree><sp><p><r><t>visible</t></r></p></sp></spTree></sld>",
        }
    )
    result = parse(data)
    assert result.success
    assert plain_text(result.blocks) == "visible"
    assert result.blocks[0].source.page == 1


@pytest.mark.parametrize(
    "data,code",
    [
        (b"", "UNSUPPORTED_FORMAT"),
        (b"PKbroken", "INVALID_FILE"),
        (b"<HWPML><BODY>", "INVALID_FILE"),
        (b'<!DOCTYPE HWPML [<!ENTITY a "bad">]><HWPML>&a;</HWPML>', "INVALID_FILE"),
    ],
)
def test_invalid_inputs_have_explicit_failures(data, code):
    result = parse(data)
    assert not result.success
    assert result.error_code == code


def test_resource_limits_and_unknown_options():
    assert parse(b"A" * 20, ParseOptions(max_input_bytes=10)).error_code == "RESOURCE_LIMIT"
    with pytest.raises(TypeError):
        ParseOptions(unknown=True)
    with pytest.raises(ValueError):
        ParseOptions(pages=(0,))
    result = parse(hwpx("<p><run><t>CPU</t></run></p>"), ParseOptions(max_expanded_bytes=10))
    assert result.error_code == "RESOURCE_LIMIT"


def test_overlapping_or_huge_table_is_rejected():
    with pytest.raises(ParseError, match="Overlapping"):
        table_from_cells(1, 2, [(0, 0, Cell("CPU", col_span=2)), (0, 1, Cell("RAM"))], ParseOptions())
    with pytest.raises(ParseError, match="oversized"):
        table_from_cells(1000, 1000, [], ParseOptions())


def test_parse_uses_bytes_signature_not_file_suffix(tmp_path):
    path = tmp_path / "wrong.pdf"
    path.write_bytes(hwpx("<p><run><t>CPU</t></run></p>"))
    assert parse(path).file_type == "hwpx"


def test_parse_runtime_has_no_node_dependency(monkeypatch):
    import subprocess

    def reject(*args, **kwargs):
        raise AssertionError("Parser must not spawn a process")

    monkeypatch.setattr(subprocess, "run", reject)
    assert parse(simple_pdf()).success
    assert parse(hwpx("<p><run><t>CPU</t></run></p>")).success
