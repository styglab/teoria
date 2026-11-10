"""Restore omitted corner quotes only when both complementary glyphs are visible."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from kory_parser import ocr_punctuation as punctuation
from kory_parser.ocr_punctuation import quote_word_boxes


def case(opening=True, closing="corner", text="K]z", scale=1):
    image = Image.new("L", (130, 50), 255)
    draw = ImageDraw.Draw(image)
    if opening:
        draw.rectangle((5, 5, 16, 8), fill=0)
        draw.rectangle((5, 5, 8, 24), fill=0)
    if closing != "none":
        draw.rectangle((88, 26 if closing == "corner" else 5, 91, 45), fill=0)
        draw.rectangle((80, 42, 91, 45), fill=0)
        if closing == "square":
            draw.rectangle((80, 5, 91, 8), fill=0)

    def box(x0, y0, x1, y1):
        return [
            [x0 * scale, y0 * scale],
            [x1 * scale, y0 * scale],
            [x1 * scale, y1 * scale],
            [x0 * scale, y1 * scale],
        ]

    words = (("K", 0.9, box(30, 0, 60, 50)), ("]", 0.9, box(75, 0, 97, 50)), ("z", 0.9, box(100, 0, 130, 50)))
    result = SimpleNamespace(txts=(text,), boxes=[box(0, 0, 130, 50)], word_results=(words,))
    return image.resize((130 * scale, 50 * scale)), result


@pytest.mark.parametrize("scale", [1, 2, 3])
def test_complementary_pixel_glyphs_restore_the_missing_pair(scale):
    image, result = case(scale=scale)
    punctuation.restore_image_corner_quotes(image, result)
    assert result.txts == ("「K」z",)


@pytest.mark.parametrize("opening,closing", [(False, "corner"), (True, "square"), (True, "none")])
def test_incomplete_or_square_evidence_preserves_recognized_text(opening, closing):
    image, result = case(opening, closing)
    punctuation.restore_image_corner_quotes(image, result)
    assert result.txts == ("K]z",)


def test_source_spaces_are_preserved():
    image, result = case(text="  K] z ")
    punctuation.restore_image_corner_quotes(image, result)
    assert result.txts == ("  「K」 z ",)


@pytest.mark.parametrize("text", ["Q]z", "K]]z", "[K]z"])
def test_ambiguous_or_unaligned_recognition_is_preserved(text):
    image, result = case(text=text)
    punctuation.restore_image_corner_quotes(image, result)
    assert result.txts == (text,)


def test_coordinate_adapter_selects_unmatched_closing_corner_candidates():
    @dataclass
    class Recognition:
        txts: tuple
        scores: list
        word_results: tuple

    class Boxes:
        def __getitem__(self, indices):
            return indices

    calls = []

    def convert(images, boxes, recognition):
        calls.append(recognition.txts)
        return ((("]", 0.9, [[1, 1]]),),)

    quote_word_boxes(convert, ["image"], Boxes(), Recognition(("K]z",), [0.9], ("raw",)))
    assert calls == [("K]z",)]
