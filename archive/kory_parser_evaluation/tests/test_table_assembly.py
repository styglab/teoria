"""Avoid disposable blank cells while retaining strict table geometry contracts."""

from unittest.mock import patch

import pytest

from kory_parser.models import Cell, ParseError, ParseOptions, SourceRef, table_from_cells


def test_dense_tables_do_not_construct_overwritten_blank_cells():
    addressed = [(r, c, Cell(f"{r}:{c}")) for r in range(64) for c in range(16)]
    with patch("kory_parser.models.Cell", wraps=Cell) as constructed:
        table = table_from_cells(64, 16, addressed, ParseOptions())
    assert table.cells[63][15] is addressed[-1][2]
    assert constructed.call_count == 0


def test_sparse_merged_cells_and_blank_cells_remain_independent():
    source = SourceRef("sheet", "A1")
    anchor = Cell("merged", row_span=2, col_span=2, source=source)
    table = table_from_cells(
        3, 3, [(0, 0, anchor), (0, 2, Cell("right"))], ParseOptions(keep_trailing_empty_cols=True)
    )
    assert table.cells[0][0] is anchor
    assert table.cells[0][0].source == source
    assert table.cells[0][1].covered and table.cells[1][0].covered and table.cells[1][1].covered
    assert not table.cells[2][0].covered
    table.cells[2][0].blocks.append(object())
    assert table.cells[2][1].blocks == []
    assert table.cells[1][2].blocks == []


def test_overlapping_anchors_and_covered_positions_still_raise():
    for addressed in (
        [(0, 0, Cell("a")), (0, 0, Cell("b"))],
        [(0, 0, Cell("a", col_span=2)), (0, 1, Cell("b"))],
        [(1, 1, Cell("first")), (0, 0, Cell("later", row_span=2, col_span=2))],
    ):
        with pytest.raises(ParseError, match="Overlapping table cells"):
            table_from_cells(2, 2, addressed, ParseOptions())


def test_resource_budget_and_trailing_width_contract_are_preserved():
    with (
        patch("kory_parser.models.Cell", wraps=Cell) as constructed,
        pytest.raises(ParseError, match="Invalid or oversized table grid"),
    ):
        table_from_cells(2, 2, [], ParseOptions(max_cells=3))
    assert constructed.call_count == 0
    table = table_from_cells(1, 3, [(0, 0, Cell("value", col_span=3))], ParseOptions())
    assert table.cols == 1
    assert table.cells[0][0].col_span == 1
    with pytest.raises(ParseError, match="Cell extends beyond declared table"):
        table_from_cells(1, 1, [(0, 0, Cell("wide", col_span=2))], ParseOptions())
