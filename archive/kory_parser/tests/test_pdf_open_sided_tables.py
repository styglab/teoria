"""Original PDFs with repeated row rules and open external table sides."""

import pymupdf
import pytest

from kory_parser import parse
from kory_parser.compare import block_text, normalized_text, tables_in_order


def open_tables(
    *, ragged=False, divider=True, overhang=False, rotation=0, closed=False, row_overrun=0, shaded=False
):
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    page.insert_text((30, 25), "Overview")
    for prefix, top, rows in [("A", 50, 3), ("B", 200, 2)]:
        if shaded:
            for row in range(rows):
                for left, right in [(30, 130), (130, 270)]:
                    page.draw_rect(
                        (left, top + row * 20, right, top + (row + 1) * 20),
                        color=None,
                        fill=(0.9, 0.9, 0.9),
                    )
        for index in range(rows + 1):
            right = 250 if ragged and index == 1 else 270
            page.draw_line((30 - row_overrun, top + index * 20), (right + row_overrun, top + index * 20))
        if divider:
            page.draw_line((130, top - (10 if overhang else 0)), (130, top + rows * 20))
        if closed:
            for x in (30, 270):
                page.draw_line((x, top), (x, top + rows * 20))
        for index in range(rows):
            page.insert_text((35, top + index * 20 + 13), f"{prefix}{index}", fontsize=9)
            page.insert_text((140, top + index * 20 + 13), f"V{index}", fontsize=9)
    page.insert_text((30, 150), "Intervening body remains outside both tables", fontsize=9)
    page.set_rotation(rotation)
    data = document.tobytes()
    document.close()
    return data


@pytest.mark.parametrize("rotation", [0, 180])
def test_open_sides_keep_separate_tables_cell_text_and_source_bounds(rotation):
    result = parse(open_tables(rotation=rotation))
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert sorted((t["rows"], t["cols"]) for t in tables) == [(2, 2), (3, 2)]
    values = sorted(cell["text"] for table in tables for row in table["cells"] for cell in row)
    assert values == sorted(["A0", "A1", "A2", "B0", "B1", "V0", "V1", "V2", "V0", "V1"])
    assert any(b.text == "Intervening body remains outside both tables" for b in result.blocks)
    assert all(t["geometry_source"] == "line" for t in tables)
    if rotation == 0:
        blocks = [b for b in result.blocks if b.table]
        assert [b.source.bbox for b in blocks] == [(30, 50, 270, 110), (30, 200, 270, 240)]
        assert blocks[0].table.cells[1][0].source.bbox == (30, 70, 130, 90)
    text = normalized_text(block_text(result.to_dict()["blocks"]))
    assert text.count("Overview") == 1
    assert all(text.count(value) == 1 for value in ["A0", "A1", "A2", "B0", "B1"])


@pytest.mark.parametrize("options", [{"ragged": True}, {"divider": False}, {"overhang": True}])
def test_unconfirmed_row_boundaries_remain_body_text(options):
    result = parse(open_tables(**options))
    assert result.success
    assert not tables_in_order(result.to_dict()["blocks"])
    assert "A0" in normalized_text(block_text(result.to_dict()["blocks"]))
    assert "B1" in normalized_text(block_text(result.to_dict()["blocks"]))


@pytest.mark.parametrize("row_overrun", [0, 1.2])
def test_existing_closed_tables_keep_their_grid(row_overrun):
    result = parse(open_tables(closed=True, row_overrun=row_overrun))
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(3, 2), (2, 2)]
    assert [cell["text"] for row in tables[0]["cells"] for cell in row] == [
        "A0",
        "V0",
        "A1",
        "V1",
        "A2",
        "V2",
    ]
    assert [b.source.bbox for b in result.blocks if b.table] == [(30, 50, 270, 110), (30, 200, 270, 240)]


def test_existing_shaded_grid_keeps_its_geometry():
    result = parse(open_tables(shaded=True))
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"], t["geometry_source"]) for t in tables] == [(3, 2, "fill"), (2, 2, "fill")]
