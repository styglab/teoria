"""Pages without enclosed numbers must not build a digit-coordinate index."""

import pytest

from kory_parser import pdf


def glyph(text, x):
    return {
        "text": text,
        "upright": True,
        "fontname": "Authored",
        "size": 12,
        "x0": x,
        "x1": x + 8,
        "top": 10,
        "bottom": 22,
        "doctop": 10,
    }


@pytest.mark.parametrize("texts", [("A", "1", "2"), ("○", "한", "글")])
def test_no_digit_index_without_both_circle_and_digit_candidates(monkeypatch, texts):
    chars = [glyph(text, i * 10) for i, text in enumerate(texts)]

    def unexpected(*args):
        raise AssertionError("Enclosed-number lookup has no eligible inputs")

    monkeypatch.setattr(pdf, "CharacterIndex", unexpected)
    normalized, composed = pdf.normalize_glyphs(chars)
    assert normalized == chars and composed == 0
    assert all(a is not b for a, b in zip(normalized, chars))


def test_source_glyph_copies_keep_null_cleanup_and_deduplication():
    chars = [glyph("A\x00", 0), glyph("A", 0), glyph("\x00", 20), glyph("B", 30)]
    normalized, composed = pdf.normalize_glyphs(chars)
    assert [c["text"] for c in normalized] == ["A", "B"] and composed == 0
    normalized[0]["text"] = "changed"
    assert chars[0]["text"] == "A\x00"


def test_digit_composition_still_uses_source_geometry():
    circle = glyph("○", 0)
    circle.update(x1=24, bottom=34, size=24)
    digit = glyph("3", 8)
    normalized, composed = pdf.normalize_glyphs([circle, digit])
    assert composed == 1 and len(normalized) == 1
    assert normalized[0]["text"] == "③"
    assert normalized[0]["x0"] == 0 and normalized[0]["x1"] == 24
