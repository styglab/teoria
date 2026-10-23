"""Single-engine installation, native coordinates and conservative glyph recovery."""

import builtins
import io

import pymupdf
import pytest
from fontTools.ttLib import TTFont

from kory_parser import ParseOptions, parse
from kory_parser.pdf import paragraph_lines
from kory_parser.pdf_fonts import family, glyph_text, outline_signature
from kory_parser.pdf_native import load_native_page

from .test_pdf_geometry import clipped_text, pdf, ruled_grid
from .test_pdf_text_optimization import char
from .test_pdf_upgrade import font_bytes


def test_parse_works_when_retired_pdf_engines_cannot_be_imported(monkeypatch):
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name.split(".")[0] in {"pdfplumber", "pdfminer", "pypdfium2"}:
            raise AssertionError(f"Retired engine imported: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    stream = ruled_grid()
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += clipped_text(x, y, 100, 50, value)
    result = parse(pdf(stream))
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert [c.text for row in table.cells for c in row] == ["CPU", "32", "RAM", "64"]
    assert ParseOptions().pdf_backend == "pymupdf"
    with pytest.raises(ValueError, match="Only the pymupdf"):
        ParseOptions(pdf_backend="pdfplumber")


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_clip_and_glyphs_share_display_coordinates(rotation):
    with pymupdf.open(stream=pdf(clipped_text(40, 150, 100, 50, "CPU")), filetype="pdf") as doc:
        native = doc[0]
        native.set_rotation(rotation)
        expected = pymupdf.Rect(40, 100, 140, 150) * native.rotation_matrix
        page = load_native_page(native, ParseOptions())
        actual = [(x0, page.height - y1, x1, page.height - y0) for x0, y0, x1, y1 in page.clips]
        assert any(tuple(box) == pytest.approx(tuple(expected)) for box in actual)
        assert all(
            expected.contains(pymupdf.Point((c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2))
            for c in page.chars
        )


def test_exact_outline_lookup_requires_matching_font_family_and_shape(monkeypatch):
    import kory_parser.pdf_fonts as fonts

    with TTFont(io.BytesIO(font_bytes())) as font:
        font["cmap"].tables.clear()
        signature = outline_signature(font, "mark")
        monkeypatch.setattr(fonts, "GLYPH_MAPS", {"ReviewedFamily": {signature: "△"}})
        assert glyph_text(font, 2, "ReviewedFamily") == "△"
        assert glyph_text(font, 2, "DifferentFamily") is None
        font["glyf"]["mark"].coordinates[0] = (1, 0)
        assert glyph_text(font, 2, "ReviewedFamily") is None
        assert glyph_text(font, 0, "ReviewedFamily") is None


def test_legacy_font_alias_is_decoded_before_outline_lookup():
    assert family("ABCDEF+ÇÑÄÄ¹ÙÅÁ-WinCharSetFFFF-H2") == "한컴바탕"
    assert family("ABCDEF+TestFont") == "TestFont"


def test_legacy_ascenders_do_not_split_same_baseline_foreign_text():
    letters = [char("가", 0, 10), char("授", 6, 17), char("나", 12, 10)]
    for c in letters:
        c["layout_top"] = 10
    result = paragraph_lines(letters, 1)
    assert len(result) == 1
    assert "".join(result[0].text.split()) == "가授나"
    assert result[0].source.bbox == (0, 10, 17, 27)


def test_ocr_rasterization_uses_mupdf_and_requested_page(monkeypatch):
    from kory_parser import ocr

    with pymupdf.open() as doc:
        doc.new_page(width=100, height=200)
        page = doc.new_page(width=150, height=250)
        page.set_rotation(90)
        data = doc.tobytes()
    seen = []

    def recognize(image, part, page_number, scale):
        seen.append((image.mode, image.size, part, page_number, scale))
        return []

    monkeypatch.setattr(ocr, "recognize", recognize)
    assert ocr.ocr_pdf_page(data, 2, ParseOptions(ocr=True)) == []
    assert seen == [("RGB", (500, 300), "pdf", 2, 2)]


def test_pdf_info_metadata_preserves_standard_and_custom_field_names():
    with pymupdf.open(stream=pdf(b"BT /F1 12 Tf 40 250 Td (Text) Tj ET"), filetype="pdf") as doc:
        doc.set_metadata({"title": "Specification", "author": "Author"})
        _, info = doc.xref_get_key(-1, "Info")
        doc.xref_set_key(int(info.split()[0]), "CustomRevision", "7")
        data = doc.tobytes()
    result = parse(data)
    assert result.metadata == {"Title": "Specification", "Author": "Author", "CustomRevision": 7}
