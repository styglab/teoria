"""Page rotation is constant during primitive extraction, including rotated coordinates."""

import pymupdf
import pytest

from kory_parser.models import ParseOptions
from kory_parser.pdf_native import load_native_page


class RotationReads:
    def __init__(self, page):
        self.page = page
        self.reads = 0

    @property
    def rotation(self):
        self.reads += 1
        return self.page.rotation

    def __getattr__(self, name):
        return getattr(self.page, name)


def test_rotation_property_reads_are_bounded_per_page():
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=800)
        for row in range(30):
            page.insert_text((20, 30 + row * 16), "constant rotation " * 5, fontsize=8)
        monitored = RotationReads(page)
        actual = load_native_page(monitored, ParseOptions())
        assert len(actual.chars) > 2000
        # Native rotation lookup must not be repeated for every glyph or box.
        assert monitored.reads <= 4


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_glyphs_and_drawings_keep_display_coordinates(rotation):
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=500)
        page.insert_text((30, 60), "Rotation", fontsize=12)
        page.draw_rect(pymupdf.Rect(20, 100, 160, 180))
        page.set_rotation(rotation)
        char = page.get_text("rawdict", flags=0)["blocks"][0]["lines"][0]["spans"][0]["chars"][0]
        expected_char = pymupdf.Rect(char["bbox"]) * page.rotation_matrix
        expected_rect = pymupdf.Rect(20, 100, 160, 180) * page.rotation_matrix
        actual = load_native_page(page, ParseOptions())
        glyph = actual.chars[0]
        assert glyph["text"] == "R"
        assert (glyph["x0"], glyph["top"], glyph["x1"], glyph["bottom"]) == pytest.approx(
            tuple(expected_char)
        )
        rect = actual.rects[0]
        assert (rect["x0"], rect["top"], rect["x1"], rect["bottom"]) == pytest.approx(tuple(expected_rect))
        assert actual.width == page.rect.width
        assert actual.height == page.rect.height
