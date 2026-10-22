"""Optimized glyph operations must preserve the established extraction semantics."""

import hashlib
import json
import random

import pytest

from teoria_docparse.pdf_text import CharacterIndex, dedupe_glyphs


def char(text, x, y, *, font="F1", size=10, upright=True, tag=0):
    return {
        "text": text,
        "x0": x,
        "x1": x + 5,
        "top": y,
        "bottom": y + 10,
        "doctop": y,
        "fontname": font,
        "size": size,
        "upright": upright,
        "tag": tag,
    }


@pytest.mark.parametrize("tolerance", [0, 0.3, 1])
def test_dedupe_preserves_pdfplumber_clusters_and_input_tie_breaking(tolerance):
    # Frozen outputs from pdfplumber 0.11.10, captured before removing that engine.
    expected = {
        0: "82d6ca1dd5380f6548c56d01e04dfb8225cd3d55e0d47995ca65ca7f037febe9",
        0.3: "5ee8bc4833ee93c6d3a0e4aea6aa5a3db2d3db99cc1acb0e71f0fe1f77bd04c0",
        1: "434377c0fd1560719304a0b60db77ba12ad70874ef2aa0cad030ce30b0823287",
    }
    rng = random.Random(803)
    outputs = []
    for iteration in range(20):
        chars = []
        for i in range(64):
            c = char(
                rng.choice("가나다ABC"),
                rng.randrange(8) * 10 + rng.choice([0, 0.3, 0.6]),
                rng.randrange(5) * 12 + rng.choice([0, 0.3, 0.6]),
                font=rng.choice(["F1", "F2"]),
                size=rng.choice([10, 12]),
                upright=rng.choice([True, False]),
                tag=i,
            )
            chars.extend([c, dict(c, x0=c["x0"] + 0.15, x1=c["x1"] + 0.15, tag=i + 100)])
        rng.shuffle(chars)
        outputs.append([c["tag"] for c in dedupe_glyphs(chars, tolerance)])
    assert hashlib.sha256(json.dumps(outputs).encode()).hexdigest() == expected[tolerance]


def test_transitive_clusters_keep_the_topmost_then_leftmost_original_glyph():
    chars = [char("A", x, y, tag=i) for i, (x, y) in enumerate([(0.6, 0.6), (0.3, 0.3), (0, 0)])]
    assert dedupe_glyphs(chars) == [chars[2]]
    assert dedupe_glyphs([chars[0], chars[0]]) == [chars[0]]
    assert dedupe_glyphs([]) == []


def test_character_index_matches_center_ownership_and_source_order():
    rng = random.Random(51)
    chars = [char(str(i), rng.randrange(100), rng.randrange(200), tag=i) for i in range(300)]
    rng.shuffle(chars)
    index = CharacterIndex(chars)
    for _ in range(100):
        x, y = rng.randrange(100), rng.randrange(200)
        box = (x, y, x + rng.randrange(1, 60), y + rng.randrange(1, 60))
        expected = [
            c
            for c in chars
            if box[0] <= (c["x0"] + c["x1"]) / 2 < box[2] and box[1] <= (c["top"] + c["bottom"]) / 2 < box[3]
        ]
        assert index.within(box) == expected
    assert index.within((0, 0, 0, 0)) == []
    assert CharacterIndex([]).within((0, 0, 100, 100)) == []


def test_digit_search_includes_the_circle_boundary_without_changing_cell_ownership():
    chars = [char("2", 5, 10)]
    index = CharacterIndex(chars)
    box = (0, 0, 7.5, 15)
    assert index.within(box) == []
    assert index.within(box, include_boundary=True) == chars


def test_native_normalizes_negative_rectangle_coordinates():
    pytest.importorskip("pymupdf")
    from teoria_docparse import ParseOptions, parse

    from .test_pdf_geometry import pdf, ruled_grid

    stream = ruled_grid()
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += f"q {x + 100} {y + 50} -100 -50 re W n BT /F1 10 Tf {x + 5} {y + 25} Td ({value}) Tj ET Q\n".encode()
    result = parse(pdf(stream), ParseOptions(pdf_backend="pymupdf"))
    table = next(b.table for b in result.blocks if b.table)
    assert (table.rows, table.cols) == (2, 2)
    assert [c.text for row in table.cells for c in row] == ["CPU", "32", "RAM", "64"]
