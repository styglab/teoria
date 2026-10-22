"""Recover adjacent form rows and page continuations using geometry and visible seams."""

import re
from dataclasses import replace

from .models import Block, Diagnostic, ParseOptions, table_from_cells
from .pdf_geometry import visible_cell_edges
from .pdf_layout import anchors, pdf_cell_text


def same_width(a, b, tolerance=1.5):
    return abs(a[0] - b[0]) <= tolerance and abs(a[2] - b[2]) <= tolerance


def append_row(head, tail, options):
    """A full-width box below a form is one merged row; source regions stay separate."""
    grid = head.table
    cell = tail.table.cells[0][0]
    addressed = anchors(grid) + [(grid.rows, 0, replace(cell, col_span=grid.cols))]
    merged = table_from_cells(grid.rows + 1, grid.cols, addressed, options)
    merged.geometry_source = grid.geometry_source
    merged.regions = grid.regions + tail.table.regions
    head.table = merged
    if head.source.page == tail.source.page:
        a, b = head.source.bbox, tail.source.bbox
        head.source = replace(head.source, bbox=(a[0], a[1], a[2], b[3]))


def numbered_continuation(head, tail):
    marker = r"(\d{1,3}|[a-zA-Z]|[가나다라마바사아자차카타파하])[.)]\s*"
    a = re.findall(r"(?:^|\n)\s*" + marker, head)
    b = re.match(r"\s*" + marker, tail)
    if not a or not b:
        return False
    left, right = a[-1], b[1]
    if left.isdecimal() and right.isdecimal():
        return int(left) + 1 == int(right)
    for alphabet in (
        "abcdefghijklmnopqrstuvwxyz",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "가나다라마바사아자차카타파하",
    ):
        if left in alphabet and right in alphabet:
            return alphabet.index(left) + 1 == alphabet.index(right)
    return False


def join_repeated_headers(blocks, page_sizes, options, warnings):
    """Join page-edge tables with identical columns and consecutive row numbers.

    Matching headers alone are insufficient: independent forms commonly repeat
    their labels. A continued first-column sequence and unobstructed page seam
    provide additional evidence before removing the repeated header row.
    """
    result = []
    last_table = None
    text_pages = {}
    for item in blocks:
        if item.source and item.text.strip():
            text_pages.setdefault(item.text.strip(), set()).add(item.source.page)

    def margin(item):
        if not item.text.strip() and item.type != "image":
            return True
        if re.fullmatch(r"[\s\-–—]*\d{1,4}[\s\-–—]*", item.text):
            return True
        ref = item.source
        if not ref or not ref.bbox or ref.page not in page_sizes:
            return False
        height = page_sizes[ref.page][1]
        at_margin = ref.bbox[3] < height * 0.12 or ref.bbox[1] > height * 0.93
        return at_margin and (item.type == "image" or len(text_pages.get(item.text.strip(), ())) >= 2)

    def header(table):
        cells = [cell for cell in table.cells[0] if not cell.covered]
        if len(cells) != table.cols or any(cell.row_span != 1 for cell in cells):
            return None
        if any(not cell.source or not cell.source.bbox for cell in cells):
            return None
        texts = tuple(re.sub(r"\s+", "", cell.text) for cell in cells)
        if sum(bool(text) for text in texts) < 2 or any(cell.blocks for cell in cells):
            return None
        return texts, [(cell.source.bbox[0], cell.source.bbox[2]) for cell in cells]

    def row_number(cell):
        text = cell.text.strip()
        return int(text) if not cell.covered and re.fullmatch(r"\d{1,6}", text) else None

    for block in blocks:
        if not block.table:
            result.append(block)
            if not margin(block):
                last_table = None
            continue
        tail = block.table
        ref = block.source
        head_block = last_table
        last_table = block
        if not head_block or tail.rows < 2 or tail.cols < 2 or not ref or not ref.bbox:
            result.append(block)
            continue
        head = head_block.table
        previous = head.regions[-1] if head.regions else head_block.source
        if (
            not previous
            or not previous.bbox
            or ref.page != previous.page + 1
            or tail.cols != head.cols
            or not same_width(previous.bbox, ref.bbox)
            or previous.bbox[3] < page_sizes[previous.page][1] * 0.83
            or ref.bbox[1] > page_sizes[ref.page][1] * 0.17
        ):
            result.append(block)
            continue
        first, second = header(head), header(tail)
        numbers = [row_number(row[0]) for row in head.cells[1:]]
        numbers = [number for number in numbers if number is not None]
        next_number = row_number(tail.cells[1][0])
        if (
            not first
            or not second
            or first[0] != second[0]
            or any(abs(a - b) > 1.5 for pair, other in zip(first[1], second[1]) for a, b in zip(pair, other))
            or not numbers
            or next_number != numbers[-1] + 1
        ):
            result.append(block)
            continue
        addressed = anchors(head) + [(head.rows + r - 1, c, cell) for r, c, cell in anchors(tail) if r]
        joined = table_from_cells(head.rows + tail.rows - 1, head.cols, addressed, options)
        joined.geometry_source = head.geometry_source
        joined.regions = head.regions + tail.regions
        head_block.table = joined
        last_table = head_block
        warnings.append(
            Diagnostic(
                "REPEATED_TABLE_HEADER_MERGED", "Continued numbered table; repeated header removed", ref
            )
        )
    return result


def join_pdf_parts(
    blocks, boundary_parts, edge_indexes, page_sizes, options: ParseOptions, boundary_text=None
):
    boundary_text = boundary_text or {}
    removed = set()
    joined_into = {}
    # Nearest preceding table only. A heading or body paragraph between boxes blocks a join.
    for j, tail in enumerate(blocks):
        if not tail.table or tail.table.rows != 1 or tail.table.cols != 1 or not tail.source:
            continue
        if not tail.source.bbox:
            continue
        i = j - 1
        between = []
        while i >= 0 and not blocks[i].table:
            between.append(blocks[i])
            i -= 1
        while i in joined_into:
            i = joined_into[i]
        if i < 0 or i in removed:
            continue
        head = blocks[i]
        if not head.source or not head.source.bbox:
            continue
        last_region = head.table.regions[-1] if head.table.regions else head.source
        hp, tp = last_region.page, tail.source.page
        a, b = last_region.bbox, tail.source.bbox
        if not same_width(a, b):
            continue
        if hp == tp and not between and 0 <= b[1] - a[3] <= 4:
            append_row(head, tail, options)
            boundary_parts.discard(id(head))
            removed.add(j)
            joined_into[j] = i
            continue
        if tp != hp + 1 or a[3] < page_sizes[hp][1] * 0.83 or b[1] > page_sizes[tp][1] * 0.17:
            continue

        # Headers/footers may intervene, ordinary body content may not.
        def running_margin(item):
            if item.type == "image" or not item.text.strip():
                return True
            if re.fullmatch(r"[\s\-–—]*\d{1,4}[\s\-–—]*", item.text):
                return True
            return any(
                other is not item
                and other.text == item.text
                and other.source
                and item.source
                and other.source.page != item.source.page
                for other in blocks
            )

        if any(not running_margin(x) for x in between):
            continue
        if head.table.cols == 1 and numbered_continuation(
            "\n".join(cell.text for row in head.table.cells for cell in row if not cell.covered),
            tail.table.cells[0][0].text,
        ):
            append_row(head, tail, options)
            boundary_parts.discard(id(head))
            removed.add(j)
            joined_into[j] = i
            continue
        # A cell may span a page even when the surrounding table has several columns.
        for r, c, cell in anchors(head.table):
            if r + cell.row_span != head.table.rows or not cell.source or not cell.source.bbox:
                continue
            if not same_width(cell.source.bbox, b):
                continue
            _top, bottom, left, right = visible_cell_edges(cell.source.bbox, edge_indexes[hp])
            nt, _nb, nl, nr = visible_cell_edges(b, edge_indexes[tp])
            ordered_full_width = cell.col_span == head.table.cols and numbered_continuation(
                cell.text, tail.table.cells[0][0].text
            )
            if not ordered_full_width and (bottom or nt or not (left and right and nl and nr)):
                continue
            addition = tail.table.cells[0][0]
            cell.blocks = (cell.blocks or [Block("paragraph", cell.text, source=cell.source)]) + (
                addition.blocks or [Block("paragraph", addition.text, source=addition.source)]
            )
            cell.text = pdf_cell_text(cell.blocks)
            head.table.regions.extend(tail.table.regions)
            removed.add(j)
            joined_into[j] = i
            break
    result = []
    for index, block in enumerate(blocks):
        if index in removed:
            continue
        if id(block) in boundary_parts and id(block) in boundary_text:
            result.extend(boundary_text[id(block)])
        elif id(block) in boundary_parts:
            cell = block.table.cells[0][0]
            result.extend(
                cell.blocks
                or [
                    Block("paragraph", line, source=cell.source)
                    for line in cell.text.split("\n")
                    if line.strip()
                ]
            )
        else:
            result.append(block)
    result.sort(
        key=lambda b: (
            (b.source.page, b.source.bbox[1], b.source.bbox[0]) if b.source and b.source.bbox else (0, 0, 0)
        )
    )
    return result
