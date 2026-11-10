"""Authored pixel evidence: curved quotes must not replace straight ticks blindly."""

from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from kory_parser import ocr


def glyph(kind, scale=1):
    image = Image.new("L", (24, 40), 255)
    draw = ImageDraw.Draw(image)
    if kind == "open":
        draw.polygon([(13, 2), (11, 2), (8, 8), (8, 13), (14, 13), (14, 8), (10, 8)], fill=0)
    elif kind == "close":
        draw.polygon([(8, 2), (14, 2), (14, 7), (11, 13), (9, 13), (12, 7), (8, 7)], fill=0)
    elif kind == "straight":
        draw.rectangle((10, 2, 12, 13), fill=0)
    elif kind == "noise":
        draw.point((12, 4), fill=0)
    return image.resize((24 * scale, 40 * scale))


@pytest.mark.parametrize("kind,expected", [("open", "‘"), ("close", "’"), ("straight", "'"), ("noise", "'")])
@pytest.mark.parametrize("scale", [1, 2, 3])
def test_quote_requires_pixel_evidence(kind, expected, scale):
    image = glyph(kind, scale)
    result = SimpleNamespace(
        txts=("A'B",),
        word_results=(
            (
                ("A", 0.9, None),
                ("'", 0.9, [[0, 0], [image.width, 0], [image.width, image.height], [0, image.height]]),
                ("B", 0.9, None),
            ),
        ),
    )
    ocr._restore_image_quotes(image, result)
    assert result.txts == (f"A{expected}B",)


def test_unaligned_or_missing_character_boxes_preserve_text():
    for words in (None, ((("wrong", 0.9, None),),)):
        result = SimpleNamespace(txts=("A'B",), word_results=words)
        ocr._restore_image_quotes(glyph("open"), result)
        assert result.txts == ("A'B",)


def test_uncertain_rotated_glyph_is_preserved():
    image = glyph("open").transpose(Image.Transpose.ROTATE_90)
    result = SimpleNamespace(
        txts=("'",),
        word_results=(
            (("'", 0.9, [[0, 0], [image.width, 0], [image.width, image.height], [0, image.height]]),),
        ),
    )
    ocr._restore_image_quotes(image, result)
    assert result.txts == ("'",)
