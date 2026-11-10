import struct

from kory_parser import parse
from kory_parser.hwp_binary import Record, hwp_text
from kory_parser.hwp_numbering import HwpDocInfo, Numbering, NumberingState, format_number

from .document_fixtures import zip_document


def test_hwp_numbering_nested_reset_and_id_history():
    state = NumberingState()
    definition = Numbering(["^1.", "^1.^2."] + [""] * 5, ["DIGIT"] * 7)
    assert state.prefix(1, 0, definition) == "1."
    assert state.prefix(1, 1, definition) == "1.1."
    assert state.prefix(1, 1, definition) == "1.2."
    assert state.prefix(1, 0, definition) == "2."
    assert state.prefix(1, 1, definition) == "2.1."
    assert state.prefix(2, 0, definition) == "1."
    assert state.prefix(1, 0, definition) == "3."


def test_hwp_numbering_start_and_circled_display():
    state = NumberingState()
    definition = Numbering(["^1"] + [""] * 6, ["CIRCLED_DIGIT"] * 7, [2] * 7)
    assert state.prefix(1, 0, definition) == "②"
    assert state.prefix(1, 0, definition) == "③"
    assert format_number(15, "HANGUL_SYLLABLE") == "거"
    assert format_number(21, "CIRCLED_DIGIT") == "㉑"


def test_hwp_doc_info_bullet_definition():
    para = bytearray(32)
    struct.pack_into("<I", para, 0, 3 << 23)
    struct.pack_into("<H", para, 30, 1)
    info = HwpDocInfo.from_records(
        [Record(0x19, 0, bytes(para), 0), Record(0x18, 0, bytes(12) + "-".encode("utf-16le"), 0)]
    )
    assert info.heading(0) == ("-", None)


def test_field_placeholder_requires_exact_guide_match():
    begin = struct.pack("<H", 3) + b"klc%" + bytes(10)
    end = struct.pack("<H", 4) + bytes(14)
    data = (
        "before ".encode("utf-16le") + begin + "guide".encode("utf-16le") + end + " after".encode("utf-16le")
    )
    assert hwp_text(data, field_guides=["guide"]) == "before  after"
    assert hwp_text(data, field_guides=["other"]) == "before guide after"


def test_hwpx_numbering_preserves_counter_zero_and_bullet():
    data = zip_document(
        {
            "Contents/header.xml": '<head><bullet id="1" char="ㅇ"/><numbering id="2"><paraHead level="1" numFormat="DIGIT" start="0">^1.</paraHead></numbering>'
            '<paraPr id="1"><heading type="BULLET" level="0" idRef="1"/></paraPr>'
            '<paraPr id="2"><heading type="NUMBER" level="0" idRef="2"/></paraPr></head>',
            "Contents/section0.xml": '<sec><p paraPrIDRef="1"><run><t>CPU</t></run></p>'
            '<p paraPrIDRef="2"><run><t>A</t></run></p><p paraPrIDRef="2"><run><t>B</t></run></p></sec>',
        }
    )
    result = parse(data)
    assert result.success
    assert [b.text for b in result.blocks] == ["ㅇ CPU", "0. A", "1. B"]
