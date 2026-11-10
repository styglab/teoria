"""Malformed external sheet labels must not erase independent cached worksheet values."""

import io
import struct
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import xlrd
import xlwt
from xlwt.CompoundDoc import XlsDoc

from kory_parser import ParseOptions, parse


def workbook(*, broken_sheet=True, broken_url=False):
    book = xlwt.Workbook()
    for name, label, value in (("First", "Alpha", 7), ("Second", "Beta", 13)):
        sheet = book.add_sheet(name)
        sheet.write(0, 0, "Item")
        sheet.write(0, 1, "Qty")
        sheet.write(1, 0, label)
        sheet.write(1, 1, value)
    stream = bytearray(book.get_biff_data())
    url = struct.pack("<H", 1) + b"\x01\x00\xd8" if broken_url else struct.pack("<H", 5) + b"\x00other"
    sheet_name = (
        struct.pack("<H", 1) + b"\x01\x00\xd8" if broken_sheet else struct.pack("<H", 5) + b"\x00Sheet"
    )
    body = struct.pack("<H", 1) + url + sheet_name
    record = struct.pack("<HH", 0x1AE, len(body)) + body
    pos = 0
    while pos + 4 <= len(stream):
        kind, size = struct.unpack_from("<HH", stream, pos)
        if kind == 0x85:
            offset = struct.unpack_from("<I", stream, pos + 4)[0]
            struct.pack_into("<I", stream, pos + 4, offset + len(record))
        if kind == 0xA:
            break
        pos += 4 + size
    stream[pos:pos] = record
    out = io.BytesIO()
    XlsDoc().save(out, bytes(stream))
    return out.getvalue()


def test_cached_values_survive_a_bad_external_sheet_name():
    result = parse(workbook())
    assert result.success and result.page_count == 2
    assert [b.table.cells[1][1].text for b in result.blocks if b.table] == ["7", "13"]
    assert [w.code for w in result.warnings] == ["XLS_EXTERNAL_NAMES_SKIPPED"]


def test_valid_external_metadata_keeps_normal_path():
    result = parse(workbook(broken_sheet=False))
    assert result.success and not result.warnings


def test_recovery_keeps_page_selection():
    result = parse(workbook(), ParseOptions(pages=(2,)))
    assert result.success and result.page_count == 2
    assert [b.text for b in result.blocks if b.type == "heading"] == ["Second"]
    assert result.blocks[1].table.cells[1][0].text == "Beta"


def test_recovery_keeps_cell_budget():
    result = parse(workbook(), ParseOptions(max_cells=1))
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_url_decoding_failure_is_not_hidden():
    result = parse(workbook(broken_url=True))
    assert not result.success and result.error_code == "INVALID_FILE"


def test_unrelated_sst_unicode_error_stays_a_failure():
    error = UnicodeDecodeError("utf-16-le", b"\x00\xd8", 0, 2, "unpaired surrogate")
    with patch.object(xlrd.book.Book, "handle_sst", side_effect=error):
        result = parse(workbook(broken_sheet=False))
    assert not result.success and result.error_code == "INVALID_FILE"


def test_parallel_readers_do_not_change_global_xlrd_methods():
    original = xlrd.book.Book.handle_supbook
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(parse, [workbook(), workbook(broken_sheet=False)]))
    assert all(r.success for r in results)
    assert not results[1].warnings
    assert xlrd.book.Book.handle_supbook is original
