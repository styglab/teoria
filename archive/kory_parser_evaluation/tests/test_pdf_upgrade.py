"""Source-grounded structure, continuation boundaries and alternate backend checks."""

import io
from types import SimpleNamespace

import pytest

from kory_parser import ParseOptions, parse
from kory_parser.pdf_geometry import EdgeIndex, visible_cell_edges

from .test_pdf_geometry import clipped_text, pdf, ruled_grid


def multipage_pdf(streams):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{4 + n * 2} 0 R" for n in range(len(streams)))
            + f"] /Count {len(streams)} >>"
        ).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for n, stream in enumerate(streams):
        objects.extend(
            [
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + n * 2} 0 R >>".encode(),
                f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
            ]
        )
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def continued_boxes(new_heading=False):
    a = b"40 30 200 40 re S\n" + clipped_text(40, 30, 200, 40, "1. CPU")
    b = b"40 200 200 60 re S\n" + clipped_text(40, 200, 200, 60, "2. RAM")
    if new_heading:
        b += b"BT /F1 12 Tf 40 275 Td (New document) Tj ET\n"
    return multipage_pdf([a, b])


def test_numbered_box_continuation_preserves_both_page_regions():
    result = parse(continued_boxes())
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert (table.rows, table.cols) == (2, 1)
    assert [row[0].text for row in table.cells] == ["1. CPU", "2. RAM"]
    assert [r.page for r in table.regions] == [1, 2]
    assert [row[0].source.page for row in table.cells] == [1, 2]


def test_new_heading_blocks_join_between_independent_forms():
    result = parse(continued_boxes(new_heading=True))
    assert result.success
    assert not any(b.table and b.table.rows == 2 for b in result.blocks)
    assert "New document" in result.markdown and "2. RAM" in result.markdown


def test_partial_rule_does_not_become_a_full_cell_border():
    edges = EdgeIndex([{"orientation": "h", "top": 0, "x0": 10, "x1": 100}])
    assert not visible_cell_edges((0, 0, 100, 40), edges)[0]
    complete = EdgeIndex([{"orientation": "h", "top": 0, "x0": 0, "x1": 100}])
    assert visible_cell_edges((0, 0, 100, 40), complete)[0]


def test_native_backend_keeps_dotted_clip_table_and_cell_coordinates():
    pytest.importorskip("pymupdf")
    stream = ruled_grid(dotted=True)
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += clipped_text(x, y, 100, 50, value)
    result = parse(pdf(stream), ParseOptions(pdf_backend="pymupdf"))
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert (table.rows, table.cols) == (2, 2)
    assert [c.text for row in table.cells for c in row] == ["CPU", "32", "RAM", "64"]
    assert table.cells[0][0].source.bbox == pytest.approx((40, 100, 140, 150))


def test_unresolved_font_preserves_text_and_reports_source(monkeypatch):
    from kory_parser.pdf_native import load_native_page

    def unresolved(*args):
        page = load_native_page(*args)
        page.chars[0]["text"] = "�"
        page.unresolved_glyphs = 1
        return page

    monkeypatch.setattr("kory_parser.pdf.load_native_page", unresolved)
    result = parse(pdf(b"BT /F1 12 Tf 40 250 Td (Kept text) Tj ET"))
    assert result.success and "�ept text" in result.markdown
    diagnostic = next(w for w in result.warnings if w.code == "UNRESOLVED_PDF_GLYPH")
    assert diagnostic.source.page == 1


def font_bytes():
    pytest.importorskip("fontTools")
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "blank", "mark"])
    pen = TTGlyphPen(None)
    empty = pen.glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((100, 200))
    pen.lineTo((200, 0))
    pen.closePath()
    builder.setupCharacterMap({32: "blank", 65: "mark"})
    builder.setupGlyf({".notdef": empty, "blank": empty, "mark": pen.glyph()})
    builder.setupHorizontalMetrics({n: (500, 0) for n in [".notdef", "blank", "mark"]})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "TestFont", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    stream = io.BytesIO()
    builder.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize(
    "gid,expected", [(1, {("TestFont", (10, 20)): " "}), (2, {("TestFont", (10, 20)): "A"}), (0, {})]
)
def test_unknown_unicode_only_becomes_space_for_verified_blank_outline(gid, expected):
    from kory_parser.pdf_fonts import glyph_replacements

    data = font_bytes()
    native = SimpleNamespace(
        parent=SimpleNamespace(extract_font=lambda x: (None, None, None, data)),
        get_fonts=lambda **kwargs: [(7, None, None, "TestFont")],
        get_texttrace=lambda: [{"font": "TestFont", "chars": [(65533, gid, (10, 20), None)]}],
    )
    raw = {
        "blocks": [{"lines": [{"spans": [{"font": "TestFont", "chars": [{"c": "�", "origin": (10, 20)}]}]}]}]
    }
    assert glyph_replacements(native, raw) == expected


def test_native_engine_error_is_an_explicit_failure(monkeypatch):
    pytest.importorskip("pymupdf")

    def broken(*args):
        raise RuntimeError("Native extraction failed")

    monkeypatch.setattr("kory_parser.pdf.load_native_page", broken)
    result = parse(pdf(b"BT /F1 12 Tf 40 250 Td (Recovered) Tj ET"), ParseOptions(pdf_backend="pymupdf"))
    assert not result.success and result.error_code == "INVALID_FILE"


def test_missing_pdf_dependency_is_an_explicit_parse_failure(monkeypatch):
    import builtins

    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("Optional dependency absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    result = parse(pdf(b"BT /F1 12 Tf 40 250 Td (Text) Tj ET"), ParseOptions(pdf_backend="pymupdf"))
    assert not result.success and result.error_code == "DEPENDENCY_MISSING"


def test_native_image_bytes_are_available_when_requested():
    native = pytest.importorskip("pymupdf")
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(stream, format="PNG")
    with native.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.insert_text((40, 40), "Image with text")
        page.insert_image(native.Rect(40, 60, 80, 100), stream=stream.getvalue())
        data = doc.tobytes()
    result = parse(data, ParseOptions(pdf_backend="pymupdf", images=True))
    assert result.success
    image = next(b for b in result.blocks if b.type == "image")
    import base64

    restored = Image.open(io.BytesIO(base64.b64decode(image.image_data)))
    assert restored.size == (4, 4) and image.mime_type == "image/png"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_native_page_keeps_content_and_display_coordinates(rotation):
    native = pytest.importorskip("pymupdf")
    with native.open() as doc:
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 40), "Rotated")
        page.set_rotation(rotation)
        expected = tuple(page.get_text("blocks")[0][:4])
        expected = tuple(native.Rect(expected) * page.rotation_matrix)
        data = doc.tobytes()
    result = parse(data, ParseOptions(pdf_backend="pymupdf"))
    assert result.success
    assert "".join(result.markdown.split()) == "Rotated"
    assert result.blocks[0].source.bbox == pytest.approx(expected, abs=0.001)
    assert not result.warnings
