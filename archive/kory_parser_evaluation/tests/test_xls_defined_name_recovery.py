"""Recover cached cells without interpreting broken BIFF8 defined-name formulas."""

import io
import struct
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import xlrd
import xlwt
from xlwt.CompoundDoc import XlsDoc

from kory_parser import ParseOptions, parse


def named_workbook(*, broken=True, label="Alpha", count=7):
    book = xlwt.Workbook()
    for name, text, number in (("First", label, count), ("Second", "Beta", 13)):
        sheet = book.add_sheet(name)
        sheet.write(0, 0, "Item")
        sheet.write(0, 1, "Qty")
        sheet.write(1, 0, text)
        sheet.write(1, 1, number)
    stream = bytearray(book.get_biff_data())
    # Lbl: 14-byte header, compressed name X, then declared formula bytes.
    # A missing token causes xlrd's name evaluator to index past the record.
    formula = b"" if broken else b"\x1e\x03\x00"
    body = struct.pack("<HBBHHH4B", 0, 0, 1, 1 if broken else len(formula), 0, 0, 0, 0, 0, 0)
    body += b"\x00X" + formula
    record = struct.pack("<HH", 0x18, len(body)) + body
    pos = 0
    while pos + 4 <= len(stream):
        kind, size = struct.unpack_from("<HH", stream, pos)
        if kind == 0x85:  # BoundSheet8 offsets must still point to sheet BOFs.
            offset = struct.unpack_from("<I", stream, pos + 4)[0]
            struct.pack_into("<I", stream, pos + 4, offset + len(record))
        if kind == 0x0A:  # Globals EOF; leave existing SST offsets intact.
            break
        pos += size + 4
    stream[pos:pos] = record
    output = io.BytesIO()
    XlsDoc().save(output, bytes(stream))
    return output.getvalue()


def test_broken_name_keeps_cached_sheet_values_and_reports_recovery():
    result = parse(named_workbook())
    assert result.success and result.page_count == 2
    tables = [b.table for b in result.blocks if b.table]
    assert [[[c.text for c in row] for row in t.cells] for t in tables] == [
        [["Item", "Qty"], ["Alpha", "7"]],
        [["Item", "Qty"], ["Beta", "13"]],
    ]
    assert [w.code for w in result.warnings] == ["XLS_DEFINED_NAMES_SKIPPED"]


def test_valid_names_keep_the_original_xlrd_path_without_recovery_warning():
    result = parse(named_workbook(broken=False))
    assert result.success and result.page_count == 2
    assert not result.warnings


def test_recovered_book_preserves_page_selection():
    result = parse(named_workbook(), ParseOptions(pages=(2,)))
    assert result.success and result.page_count == 2
    assert [b.text for b in result.blocks if b.type == "heading"] == ["Second"]
    assert result.blocks[1].table.cells[1][0].text == "Beta"


def test_recovery_does_not_bypass_the_grid_budget():
    result = parse(named_workbook(), ParseOptions(max_cells=1))
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_unrelated_globals_failure_stays_a_failure():
    with patch.object(xlrd.book.Book, "parse_globals", side_effect=IndexError("unrelated globals")):
        result = parse(named_workbook())
    assert not result.success and result.error_code == "INTERNAL_ERROR"


def test_parallel_normal_and_recovered_books_do_not_patch_global_xlrd_state():
    original_class = xlrd.book.Book
    inputs = [named_workbook(), named_workbook(broken=False, label="Clean", count=11)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(parse, inputs))
    assert all(result.success for result in results)
    assert results[0].blocks[1].table.cells[1][0].text == "Alpha"
    assert results[1].blocks[1].table.cells[1][0].text == "Clean"
    assert not results[1].warnings
    assert xlrd.book.Book is original_class
