"""Compact sheets retain sparse/merged coordinates with bounded axis lookups."""

from kory_parser.models import Cell, ParseOptions, SourceRef
from kory_parser.office import sheet_table


def test_compact_sheet_axis_lookup_does_not_scan_all_rows_per_cell():
    class CountedIndex(int):
        comparisons = 0

        def __lt__(self, other):
            type(self).comparisons += 1
            return int.__lt__(self, other)

        def __le__(self, other):
            type(self).comparisons += 1
            return int.__le__(self, other)

    values = {
        (CountedIndex(row * 3), col * 2): Cell(f"{row}:{col}") for row in range(256) for col in range(4)
    }
    table = sheet_table(768, 8, values, ParseOptions())
    assert (table.rows, table.cols) == (256, 4)
    assert table.cells[255][3].text == "255:3"
    # A comparison budget detects the quadratic regression without depending
    # on machine load or a wall-clock timeout.
    assert CountedIndex.comparisons < 80 * len(values)


def test_sparse_merged_cells_keep_only_occupied_axes_and_original_sources():
    source = SourceRef("xl/worksheets/sheet1.xml", "C4")
    values = {
        (3, 2): Cell("merged", row_span=6, col_span=7, source=source),
        (3, 12): Cell("right"),
        (7, 12): Cell("lower"),
        (12, 6): Cell("bottom"),
    }
    table = sheet_table(13, 13, values, ParseOptions())
    assert (table.rows, table.cols) == (3, 3)
    assert table.cells[0][0].text == "merged"
    assert (table.cells[0][0].row_span, table.cells[0][0].col_span) == (2, 2)
    assert table.cells[0][0].source == source
    assert table.cells[1][0].covered
    assert table.cells[2][1].text == "bottom"


def test_empty_merge_anchor_between_retained_axes():
    source = SourceRef("xl/worksheets/sheet1.xml", "G3")
    table = sheet_table(
        9,
        9,
        {
            (0, 0): Cell("first"),
            (4, 4): Cell("middle"),
            (8, 8): Cell("last"),
            (2, 6): Cell("", row_span=4, col_span=3, source=source),
            (1, 1): Cell("", row_span=1, col_span=1),
            (7, 0): Cell("", row_span=-3, col_span=1),
        },
        ParseOptions(),
    )
    assert (table.rows, table.cols) == (3, 3)
    assert table.cells[1][2].source == source
    assert (table.cells[1][2].row_span, table.cells[1][2].col_span) == (1, 1)
    assert table.cells[2][2].text == "last"
