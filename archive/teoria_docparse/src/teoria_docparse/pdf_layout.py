"""Visible table bands versus invisible document layout frames.

Ported from the ruledRows/bandTable approach in kordoc 4.22.15 (MIT).
Original clip coordinates remain attached to the resulting cells and paragraphs.
"""

import re
from dataclasses import replace

from .models import Block, ParseOptions, table_from_cells
from .pdf_geometry import visible_cell_edges


def anchors(table):
    return [
        (r, c, cell)
        for r, row in enumerate(table.cells)
        for c, cell in enumerate(row)
        if not cell.covered and cell.source is not None
    ]


def pdf_cell_text(blocks: list[Block]) -> str:
    parts = []
    for block in blocks:
        if block.table:
            for row in block.table.cells:
                parts.append(" ".join(cell.text for cell in row if not cell.covered and cell.text))
        elif block.text and block.type != "image":
            parts.append(block.text)
    return "\n".join(parts)


def coalesce_header_fields(block, edges, options):
    """Project invisible value fragments onto two explicitly ruled header fields.

    A header such as Field/Value can span several clipping columns used only to
    align a number, its unit and a note. Real interior rules, nested objects,
    multiline fragments and incompatible row spans prevent this projection.
    """
    table = block.table
    if table.cols < 3 or table.rows < 2:
        return block
    selected = anchors(table)
    header = [(c, cell) for r, c, cell in selected if r == 0]
    if (
        len(header) != 2
        or header[0][0] != 0
        or header[0][1].col_span != header[1][0]
        or header[1][0] + header[1][1].col_span != table.cols
        or any(cell.row_span != 1 or not re.search(r"[^\W\d_]", cell.text) for _, cell in header)
    ):
        return block
    split = header[1][0]
    field_edges = {0, split, table.cols}
    groups = {}
    spanning = []
    for r, c, cell in selected:
        if not cell.source.bbox or cell.blocks:
            return block
        rules = edges[cell.source.page] if isinstance(edges, dict) else edges
        _, _, left, right = visible_cell_edges(cell.source.bbox, rules)
        if left and c not in field_edges or right and c + cell.col_span not in field_edges:
            return block
        if r == 0 and not (left and right):
            return block
        if c < split < c + cell.col_span:
            if c != 0 or cell.col_span != table.cols:
                return block
            spanning.append((r, 0, replace(cell, col_span=2)))
        else:
            groups.setdefault((r, int(c >= split)), []).append((c, cell))
    if not any(len(group) > 1 for group in groups.values()):
        return block
    addressed = list(spanning)
    for (r, col), group in groups.items():
        group.sort(key=lambda item: item[0])
        first = group[0][1]
        if len(group) == 1:
            addressed.append((r, col, replace(first, col_span=1)))
            continue
        if any(cell.row_span != 1 or "\n" in cell.text.strip() for _, cell in group):
            return block
        boxes = [cell.source.bbox for _, cell in group]
        bbox = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        fragments = [
            Block("paragraph", cell.text, source=cell.source) for _, cell in group if cell.text.strip()
        ]
        addressed.append(
            (
                r,
                col,
                replace(
                    first,
                    text=" ".join(cell.text.strip() for _, cell in group if cell.text.strip()),
                    col_span=1,
                    blocks=fragments,
                    source=replace(first.source, bbox=bbox),
                ),
            )
        )
    projected = table_from_cells(table.rows, 2, addressed, options)
    projected.regions = table.regions
    projected.geometry_source = table.geometry_source
    return replace(block, table=projected)


def band(block, selected, begin, end, options, horizontal=None, vertical=None):
    candidates = [
        (r, c, replace(cell, row_span=min(cell.row_span, end - r)))
        for r, c, cell in selected
        if begin <= r < end
    ]
    if horizontal is not None and vertical is not None:
        lo, hi = block.table.cols, 0
        for r in range(begin, end):
            for c, visible in enumerate(vertical[r]):
                if visible:
                    lo, hi = min(lo, c), max(hi, c)
            for rr in (r, r + 1):
                for c, visible in enumerate(horizontal[rr]):
                    if visible:
                        lo, hi = min(lo, c), max(hi, c + 1)
        blank = lambda cell: not cell.text.strip() and not cell.blocks
        if lo <= hi:
            candidates = [
                (r, c, cell)
                for r, c, cell in candidates
                if c < hi and c + cell.col_span > lo or not blank(cell)
            ]
        drop = set()
        for r in range(begin, end):
            starts = [cell for rr, _, cell in candidates if rr == r]
            if (
                starts
                and all(blank(cell) for cell in starts)
                and not (any(horizontal[r]) and any(horizontal[r + 1]))
            ):
                drop.add(r)
        shift = lambda r: r - sum(d < r for d in drop)
        candidates = [
            (shift(r), c, replace(cell, row_span=shift(r + cell.row_span) - shift(r)))
            for r, c, cell in candidates
            if r not in drop and shift(r + cell.row_span) > shift(r)
        ]
    if not candidates:
        return None
    row_axis = sorted({n for r, _, cell in candidates for n in (r, r + cell.row_span)})
    col_axis = sorted({n for _, c, cell in candidates for n in (c, c + cell.col_span)})
    addressed = []
    for r, c, cell in candidates:
        row, col = row_axis.index(r), col_axis.index(c)
        addressed.append(
            (
                row,
                col,
                replace(
                    cell,
                    row_span=row_axis.index(r + cell.row_span) - row,
                    col_span=col_axis.index(c + cell.col_span) - col,
                ),
            )
        )
    table = table_from_cells(len(row_axis) - 1, len(col_axis) - 1, addressed, options)
    source = block.source
    regions = []

    def cell_sources(cell):
        if cell.source and cell.source.bbox:
            yield cell.source
        for child in cell.blocks:
            if child.source and child.source.bbox:
                yield child.source
            if child.table:
                for _, _, nested in anchors(child.table):
                    yield from cell_sources(nested)

    source_refs = [ref for _, _, cell in candidates for ref in cell_sources(cell)]
    pages = sorted({ref.page for ref in source_refs})
    for page in pages:
        refs = [ref for ref in source_refs if ref.page == page]
        boxes = [ref.bbox for ref in refs]
        bbox = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        regions.append(replace(refs[0], bbox=bbox))
    if regions:
        source = regions[0]
    table.regions = regions
    table.geometry_source = block.table.geometry_source
    return Block("table", table=table, source=source)


def visible_blocks(
    blocks: list[Block], edges: list[dict], options: ParseOptions, unframed_text=None
) -> list[Block]:
    result = []
    for block in blocks:
        if block.table is None:
            result.append(block)
            continue
        table = block.table
        selected = anchors(table)
        for _, _, cell in selected:
            if cell.blocks:
                cell.blocks = visible_blocks(cell.blocks, edges, options, unframed_text)
                cell.text = pdf_cell_text(cell.blocks)
        if table.geometry_source != "clip":
            result.append(block)
            continue
        horizontal = [[False] * table.cols for _ in range(table.rows + 1)]
        vertical = [[False] * (table.cols + 1) for _ in range(table.rows)]
        count = [0] * table.rows
        for r, c, cell in selected:
            if not cell.source.bbox:
                continue
            top, bottom, left, right = visible_cell_edges(
                cell.source.bbox, edges[cell.source.page] if isinstance(edges, dict) else edges
            )
            for col in range(c, c + cell.col_span):
                horizontal[r][col] |= top
                horizontal[r + cell.row_span][col] |= bottom
            for row in range(r, r + cell.row_span):
                vertical[row][c] |= left
                vertical[row][c + cell.col_span] |= right
                count[row] += 1
        ruled = [
            any(vertical[r]) or count[r] >= 2 and all(horizontal[r]) and all(horizontal[r + 1])
            for r in range(table.rows)
        ]
        crossed = {rr for r, _, cell in selected for rr in range(r + 1, r + cell.row_span)}
        r = 0
        while r < table.rows:
            end = r + 1
            while end in crossed:
                end += 1
            if (
                end - r > 1
                and all(horizontal[r])
                and all(horizontal[end])
                and sum(rr == r and cell.row_span == end - r for rr, _, cell in selected) >= 2
            ):
                ruled[r:end] = [True] * (end - r)
            r = end
        r = 0
        while r < table.rows:
            if ruled[r]:
                end = r + 1
                while end < table.rows and ruled[end]:
                    end += 1
                replacement = band(block, selected, r, end, options, horizontal, vertical)
                if replacement:
                    result.append(coalesce_header_fields(replacement, edges, options))
                r = end
                continue
            row = sorted(((c, cell) for rr, c, cell in selected if rr == r), key=lambda a: a[0])
            for _, cell in row:
                if cell.blocks:
                    result.extend(cell.blocks)
                elif unframed_text and (cell.source.page, cell.source.bbox) in unframed_text:
                    result.extend(unframed_text[(cell.source.page, cell.source.bbox)])
                elif cell.text.strip():
                    for line in cell.text.strip().split("\n"):
                        if line.strip():
                            result.append(Block("paragraph", line.strip(), source=cell.source))
            r += 1
    return result
