"""BIFF drawing padding must not prevent independent worksheet cell recovery."""

import io
import struct
from concurrent.futures import ThreadPoolExecutor

import pytest
import xlrd
import xlwt
from xlwt.CompoundDoc import XlsDoc

from kory_parser import ParseOptions, parse


def workbook(*, padding=b"xx", text="주석"):
    book = xlwt.Workbook()
    sheet = book.add_sheet("Cells")
    sheet.write_merge(0, 0, 0, 1, "항목")
    sheet.write(1, 0, "펌프")
    sheet.write(1, 1, 7)
    stream = bytearray(book.get_biff_data())

    def record(code, body):
        return struct.pack("<HH", code, len(body)) + body

    txo = struct.pack("<HH6sHHH", 0, 0, b"\0" * 6, len(text), 16, 0) + b"\0\0"
    runs = struct.pack("<HH4xHH4x", 0, 0, len(text), 0)
    records = (
        record(0x5D, struct.pack("<5H", 0x15, 18, 6, 1, 0) + b"\0" * 12)
        + record(0x1B6, txo)
        + record(0x3C, b"\1" + text.encode("utf-16le"))
        + record(0x3C, runs + padding)
    )
    pos = 0
    eof = []
    while pos + 4 <= len(stream):
        code, length = struct.unpack_from("<HH", stream, pos)
        if code == 0xA:
            eof.append(pos)
        pos += length + 4
    stream[eof[-1] : eof[-1]] = records
    out = io.BytesIO()
    XlsDoc().save(out, bytes(stream))
    return out.getvalue()


def test_surplus_run_bytes_recover_cells_and_merges():
    result = parse(workbook())
    assert result.success and result.page_count == 1
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (2, 2)
    assert table.cells[0][0].text == "항목" and table.cells[0][0].col_span == 2
    assert table.cells[0][1].covered
    assert [c.text for c in table.cells[1]] == ["펌프", "7"]
    assert [w.code for w in result.warnings] == ["XLS_DRAWING_TEXT_PADDING"]


def test_valid_drawing_uses_unchanged_normal_path():
    result = parse(workbook(padding=b""))
    assert result.success and not result.warnings


def test_recovered_sheet_still_obeys_cell_budget():
    result = parse(workbook(), ParseOptions(max_cells=1, sheet_layout="source"))
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_parallel_recovery_does_not_change_xlrd_global_methods():
    original = xlrd.sheet.Sheet.handle_txo
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(parse, [workbook(), workbook(padding=b"")]))
    assert all(x.success for x in results)
    assert not results[1].warnings
    assert xlrd.sheet.Sheet.handle_txo is original


@pytest.mark.parametrize("padding", [b"xx", b"xxxxxx", b"x" * 10])
def test_padding_lengths_are_not_document_specific(padding):
    assert parse(workbook(padding=padding, text="검토용 도형 설명")).success


def test_unrelated_sheet_assertion_is_not_treated_as_drawing_padding(monkeypatch):
    def fail(*args):
        raise AssertionError("unrelated worksheet failure")

    monkeypatch.setattr(xlrd.sheet.Sheet, "read", fail)
    with pytest.raises(AssertionError, match="unrelated worksheet failure"):
        parse(workbook())


def test_valid_txo_does_not_hide_an_unrelated_assertion(monkeypatch):
    def fail(*args):
        raise AssertionError("unrelated drawing assertion")

    monkeypatch.setattr(xlrd.sheet.Sheet, "handle_txo", fail)
    with pytest.raises(AssertionError):
        parse(workbook(padding=b""))
