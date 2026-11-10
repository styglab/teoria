"""A heavier double separator is one row boundary; narrow data rows survive."""

import pymupdf
import pytest

from kory_parser import parse


def ruled_table(separator_width, *, gap=1.4, rotation=0, neighboring_width=0.25, top_width=None):
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=220)
        for x in (40, 140, 240):
            page.draw_line((x, 40), (x, 160), width=neighboring_width)
        page.draw_line((40, 40), (240, 40), width=top_width or neighboring_width)
        for y in (120, 160):
            page.draw_line((40, y), (240, y), width=neighboring_width)
        for y in (80 - gap / 2, 80 + gap / 2):
            for left, right in ((40, 140), (140, 240)):
                page.draw_line((left, y), (right, y), width=separator_width)
        for text, x, y in (("Name", 50, 65), ("Value", 150, 65),
                           ("Alpha", 50, 105), ("10", 150, 105),
                           ("Beta", 50, 145), ("20", 150, 145)):
            page.insert_text((x, y), text, fontsize=9)
        page.set_rotation(rotation)
        return document.tobytes()


@pytest.mark.parametrize("rotation", [0, 180])
@pytest.mark.parametrize("gap", [1.2, 1.4])
def test_heavier_double_separator_does_not_create_an_empty_row(rotation, gap):
    result = parse(ruled_table(0.5, gap=gap, rotation=rotation))
    assert result.success
    tables = [block.table for block in result.blocks if block.table]
    assert [(table.rows, table.cols) for table in tables] == [(3, 2)]
    cells = [cell.text for row in tables[0].cells for cell in row]
    assert sorted(cells) == sorted(["Name", "Value", "Alpha", "10", "Beta", "20"])


@pytest.mark.parametrize("rotation", [0, 180])
def test_equal_weight_rules_preserve_a_narrow_empty_data_row(rotation):
    result = parse(ruled_table(0.25, rotation=rotation))
    assert result.success
    tables = [block.table for block in result.blocks if block.table]
    assert [(table.rows, table.cols) for table in tables] == [(4, 2)]
    assert any(all(not cell.text for cell in row) for row in tables[0].cells)


@pytest.mark.parametrize("rotation", [0, 180])
def test_heavy_outer_frame_does_not_turn_header_separator_into_a_row(rotation):
    result = parse(ruled_table(0.5, top_width=1, rotation=rotation))
    assert result.success
    table = next(block.table for block in result.blocks if block.table)
    assert (table.rows, table.cols) == (3, 2)


def test_wider_gap_is_not_assumed_to_be_a_double_separator():
    result = parse(ruled_table(0.5, gap=2.4))
    assert result.success
    table = next(block.table for block in result.blocks if block.table)
    assert (table.rows, table.cols) == (4, 2)
