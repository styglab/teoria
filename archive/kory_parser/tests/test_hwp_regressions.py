import struct

from kory_parser import parse
from kory_parser.models import Block, Cell, Table, plain_text

from .document_fixtures import hwp5, hwp_record


def test_memo_paragraphs_are_not_body_text():
    body = hwp_record(0x42, 0, bytes(22))
    body += hwp_record(0x43, 1, "CPU 32\r".encode("utf-16le"))
    body += hwp_record(0x5D, 1, struct.pack("<I", 1))
    body += hwp_record(0x48, 1, bytes(12))
    body += hwp_record(0x42, 1, bytes(22))
    body += hwp_record(0x43, 2, "private memo\r".encode("utf-16le"))
    result = parse(hwp5(body))
    assert result.success
    assert plain_text(result.blocks) == "CPU 32"


def test_composed_enclosed_numbers_are_restored_at_their_inline_position():
    control = struct.pack("<H", 23) + b"spct" + bytes(10)
    text = "Before ".encode("utf-16le") + control + " CPU\r".encode("utf-16le")
    data = b"spct" + struct.pack("<H", 2) + "16".encode("utf-16le") + b"\x01"
    body = hwp_record(0x42, 0, bytes(22)) + hwp_record(0x43, 1, text) + hwp_record(0x47, 1, data)
    result = parse(hwp5(body))
    assert result.success
    assert result.blocks[0].text == "Before ⑯ CPU"


def test_page_headers_and_footers_surround_body_instead_of_moving_inside_it():
    body = hwp_record(0x42, 0, bytes(22)) + hwp_record(0x43, 1, "Body\r".encode("utf-16le"))
    for control, value in [(b"daeh", "Header"), (b"toof", "Footer")]:
        body += hwp_record(0x47, 1, control)
        body += hwp_record(0x48, 2, bytes(12))
        body += hwp_record(0x42, 3, bytes(22))
        body += hwp_record(0x43, 4, (value + "\r").encode("utf-16le"))
    result = parse(hwp5(body))
    assert result.success
    assert [b.text for b in result.blocks] == ["Header", "Body", "Footer"]


def test_private_glyph_source_is_preserved_but_markdown_is_readable():
    body = hwp_record(0x42, 0, bytes(22)) + hwp_record(0x43, 1, "\ua3da CPU\r".encode("utf-16le"))
    result = parse(hwp5(body))
    assert result.success
    assert result.blocks[0].text == "\U000f03da CPU"
    assert result.markdown == "□ CPU"


def test_nested_table_plain_projection_skips_empty_layout_rows():
    inner = Table(3, 2, [[Cell("CPU"), Cell("32")], [Cell(), Cell()], [Cell("RAM"), Cell("64")]])
    blocks = [
        Block("paragraph"),
        Block("paragraph", "Before"),
        Block("table", table=inner),
        Block("paragraph"),
        Block("paragraph", "After", inline_continuation=True),
    ]
    assert plain_text(blocks) == "Before\nCPU / 32\nRAM / 64 After"
