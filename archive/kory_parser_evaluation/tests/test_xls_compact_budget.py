"""Compact oversized XLS presentation grids without weakening cell budgets."""

import io

import xlwt

from kory_parser import ParseOptions, parse


def sparse_workbook():
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sparse")
    sheet.write(0, 0, "Name")
    sheet.write(0, 4, "Count")
    sheet.write(4, 0, "Alpha")
    sheet.write(4, 4, 0)
    sheet.write(8, 0, "Beta")
    sheet.write(8, 4, 7)
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_oversized_source_grid_compacts_into_the_unchanged_budget():
    result = parse(sparse_workbook(), ParseOptions(max_cells=6))
    assert result.success
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (3, 2)
    assert [[c.text for c in row] for row in table.cells] == [
        ["Name", "Count"],
        ["Alpha", "0"],
        ["Beta", "7"],
    ]
    assert table.cells[2][1].source.anchor == "R9C5"
    assert [w.code for w in result.warnings] == ["XLS_COMPACTED_GRID"]


def test_source_layout_keeps_the_original_extent_budget():
    result = parse(sparse_workbook(), ParseOptions(max_cells=6, sheet_layout="source"))
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_actual_compact_grid_must_still_fit_the_budget():
    result = parse(sparse_workbook(), ParseOptions(max_cells=5))
    assert not result.success and result.error_code == "RESOURCE_LIMIT"


def test_in_budget_legacy_grid_output_is_preserved():
    result = parse(sparse_workbook(), ParseOptions(max_cells=45))
    assert result.success and not result.warnings
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (9, 5)
    assert table.cells[4][4].text == "0"


def test_compacted_merge_keeps_covered_positions_and_source_anchor():
    book = xlwt.Workbook()
    sheet = book.add_sheet("Merged")
    sheet.write_merge(0, 0, 0, 4, "Group")
    sheet.write(4, 0, "Left")
    sheet.write(4, 4, "Right")
    output = io.BytesIO()
    book.save(output)
    result = parse(output.getvalue(), ParseOptions(max_cells=4))
    assert result.success
    table = result.blocks[1].table
    assert (table.rows, table.cols) == (2, 2)
    assert table.cells[0][0].col_span == 2 and table.cells[0][1].covered
    assert table.cells[0][0].source.anchor == "R1C1"
    assert table.cells[1][1].source.anchor == "R5C5"


def test_page_selection_does_not_materialize_an_oversized_unselected_sheet():
    book = xlwt.Workbook()
    book.add_sheet("Skipped").write(99, 99, "Outside budget")
    book.add_sheet("Chosen").write(0, 0, "Only value")
    output = io.BytesIO()
    book.save(output)
    result = parse(output.getvalue(), ParseOptions(max_cells=1, pages=(2,)))
    assert result.success and result.page_count == 2
    assert result.blocks[0].text == "Chosen" and not result.warnings
