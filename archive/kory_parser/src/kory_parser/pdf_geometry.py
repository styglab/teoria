"""Recover cell geometry from PDF clipping operators, including borderless/nested cells.

Adjacency and containment rules adapted from kordoc 4.22.15 clip-cells.ts (MIT).
Clipping rectangles are supplied by MuPDF in page coordinates.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import cached_property
from statistics import median

from .models import ParseError, ParseOptions

Rect = tuple[float, float, float, float]


def area(box: Rect) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def inside(inner: Rect, outer: Rect, tolerance=0.5) -> bool:
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def intersection(a: Rect, b: Rect) -> float:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def cluster(values: list[float], tolerance=0.3) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [sum(group) / len(group) for group in groups]


@dataclass
class PdfGrid:
    cells: list[Rect]
    strategy: str = "clip"

    @cached_property
    def bbox(self) -> Rect:
        return (
            min(b[0] for b in self.cells),
            min(b[1] for b in self.cells),
            max(b[2] for b in self.cells),
            max(b[3] for b in self.cells),
        )


def adjacent(a: Rect, b: Rect) -> bool:
    al = lambda x, y: abs(x - y) <= 0.3
    if (abs(a[2] - b[0]) <= 0.15 or abs(b[2] - a[0]) <= 0.15) and min(a[3], b[3]) - max(a[1], b[1]) > 1.5:
        return al(a[1], b[1]) or al(a[3], b[3])
    if (abs(a[3] - b[1]) <= 0.15 or abs(b[3] - a[1]) <= 0.15) and min(a[2], b[2]) - max(a[0], b[0]) > 1.5:
        return al(a[0], b[0]) or al(a[2], b[2])
    return False


class EdgeIndex:
    """Index rules by coordinate; each cell examines nearby edges only."""

    def __init__(self, edges: list[dict]):
        self.rules = {}
        for direction, coordinate in (("h", "top"), ("v", "x0")):
            lines = sorted(
                (e for e in edges if e.get("orientation") == direction), key=lambda e: e[coordinate]
            )
            self.rules[direction] = ([e[coordinate] for e in lines], lines)

    def near(self, direction: str, position: float):
        positions, lines = self.rules[direction]
        return lines[bisect_left(positions, position - 1.6) : bisect_right(positions, position + 1.6)]


def visible_cell_edges(box: Rect, edges: list[dict] | EdgeIndex) -> tuple[bool, bool, bool, bool]:
    index = edges if isinstance(edges, EdgeIndex) else EdgeIndex(edges)

    def covered(direction, pos, lo, hi):
        intervals = []
        for edge in index.near(direction, pos):
            value = edge["top"] if direction == "h" else edge["x0"]
            if abs(value - pos) > 1.6:
                continue
            a, b = (edge["x0"], edge["x1"]) if direction == "h" else (edge["top"], edge["bottom"])
            outside = (a < lo) != (b > hi)
            a, b = max(a, lo), min(b, hi)
            if b > a and not (outside and b - a < 1.5):
                intervals.append((a, b))
        length, start, last = 0, None, lo
        for a, b in sorted(intervals):
            if start is not None and a - last <= 3:
                last = max(last, b)
            else:
                if start is not None:
                    length += last - start
                start, last = a, b
        if start is not None:
            length += last - start
        return length >= (hi - lo) * 0.6 and (hi - lo) - length <= 3

    return (
        covered("h", box[1], box[0], box[2]),
        covered("h", box[3], box[0], box[2]),
        covered("v", box[0], box[1], box[3]),
        covered("v", box[2], box[1], box[3]),
    )


def ruled_box(box: Rect, edges: list[dict]) -> bool:
    return all(visible_cell_edges(box, edges))


def decorative_strip(grid: PdfGrid, chars: list[dict], edges: EdgeIndex) -> bool:
    """A gradient's narrow paint strips are not columns of a table.

    Require a single row, glyphs crossing the narrow partitions, and no visible
    vertical rules. Shaded data cells and blank ruled entry boxes remain tables.
    """
    cells = grid.cells
    if len(cells) < 6 or max(b[1] for b in cells) - min(b[1] for b in cells) > 1.5:
        return False
    if max(b[3] for b in cells) - min(b[3] for b in cells) > 1.5:
        return False
    width = median(b[2] - b[0] for b in cells)
    glyphs = [
        c
        for c in chars
        if c["text"].strip()
        and grid.bbox[0] <= (c["x0"] + c["x1"]) / 2 <= grid.bbox[2]
        and grid.bbox[1] <= (c["top"] + c["bottom"]) / 2 <= grid.bbox[3]
    ]
    if not glyphs or width >= median(c["size"] for c in glyphs):
        return False
    if not any(c["x1"] - c["x0"] > width * 1.25 for c in glyphs):
        return False
    return not any(left or right for _, _, left, right in (visible_cell_edges(cell, edges) for cell in cells))


def grid_cell_subset(grid, other):
    return inside(grid.bbox, other.bbox, 1.5) and all(
        any(max(abs(a - b) for a, b in zip(cell, existing)) <= 1.5 for existing in other.cells)
        for cell in grid.cells
    )


def distinct_grids(grids, edges: EdgeIndex, enclosing_grids=()):
    """Keep complete grids; shading and text clips must not duplicate their cells."""
    priority = {"clip": 0, "line": 1, "fill": 2}
    ordered = sorted(
        enumerate(grids),
        key=lambda item: (
            -len(item[1].cells),
            priority.get(getattr(item[1], "strategy", "line"), 1),
            item[0],
        ),
    )
    selected = []
    context = list(grids) + list(enclosing_grids)
    for original, grid in ordered:
        if any(grid_cell_subset(grid, other) for _, other in selected):
            continue
        if (
            getattr(grid, "strategy", "") == "clip"
            and len(grid.cells) == 1
            and any(
                getattr(other, "strategy", "line") == "line"
                and len(other.cells) > 1
                and not any(inside(grid.bbox, cell, 1.5) for cell in other.cells)
                and (
                    inside(grid.bbox, other.bbox, 1.5)
                    or (
                        getattr(grid, "boundary_part", False)
                        and not ruled_box(grid.bbox, edges)
                        and intersection(grid.bbox, other.bbox) > area(grid.bbox) * 0.5
                    )
                )
                for other in context
                if other is not grid
            )
        ):
            # Broad clipping frames can overlap several real ruled cells and
            # repeat their text as a second table. Text outside the ruled grid
            # remains available to ordinary paragraph extraction.
            continue
        if getattr(grid, "strategy", "") == "fill" and any(
            getattr(other, "strategy", "line") == "line"
            and area(other.bbox) > area(grid.bbox) + 1
            and inside(grid.bbox, other.bbox, 1.5)
            and not any(inside(grid.bbox, cell, 1.5) for cell in other.cells)
            for other in context
            if other is not grid
        ):
            # Fill-derived label extents can cross several actual ruled cells.
            # A genuine nested table fits inside one enclosing cell instead.
            continue
        if (
            getattr(grid, "strategy", "") == "clip"
            and max(cell[1] for cell in grid.cells) - min(cell[1] for cell in grid.cells) <= 1.5
            and max(cell[3] for cell in grid.cells) - min(cell[3] for cell in grid.cells) <= 1.5
            and not any(
                left or right for _, _, left, right in (visible_cell_edges(c, edges) for c in grid.cells)
            )
            and any(
                inside(grid.bbox, cell, 1.5) and area(grid.bbox) < area(cell) - 1
                for other in context
                if other is not grid
                for cell in other.cells
            )
        ):
            # Separate clipping boxes around a number and a word are typography
            # inside the parent cell, with no independently ruled columns.
            continue
        if (
            getattr(grid, "boundary_part", False)
            and not ruled_box(grid.bbox, edges)
            and any(
                inside(grid.bbox, cell, 1.5) and area(grid.bbox) < area(cell) - 1
                for _, other in ordered
                if other is not grid
                for cell in other.cells
            )
        ):
            continue
        selected.append((original, grid))
    return [grid for _, grid in sorted(selected)]


def clip_grids(page, options: ParseOptions, raw_clips=None) -> list[PdfGrid]:
    if raw_clips is None:
        raw_clips = page.clips
    raw_boxes = [
        (x0, page.height - y1, x1, page.height - y0)
        for x0, y0, x1, y1 in raw_clips
        if x1 - x0 >= 4 and y1 - y0 >= 2 and (x1 - x0) * (y1 - y0) < page.width * page.height * 0.75
    ]
    return rectangular_grids(raw_boxes, page, options, "clip")


def rectangular_grids(raw_boxes: list[Rect], page, options: ParseOptions, strategy: str) -> list[PdfGrid]:
    if len(raw_boxes) > 4000:
        raise ParseError("RESOURCE_LIMIT", "Too many PDF cell rectangles")
    boxes = []
    buckets: dict[tuple[int, int], list[Rect]] = {}
    for box in raw_boxes:
        bx, by = int(box[0] // 1.5), int(box[1] // 1.5)
        nearby = [b for dx in (-1, 0, 1) for dy in (-1, 0, 1) for b in buckets.get((bx + dx, by + dy), [])]
        if any(max(abs(a - b) for a, b in zip(box, other)) <= 1.5 for other in nearby):
            continue
        buckets.setdefault((bx, by), []).append(box)
        boxes.append(box)
    can_parent = []
    for n, a in enumerate(boxes):
        can_parent.append(
            not any(
                j != n
                and not inside(b, a, 1.5)
                and not inside(a, b, 1.5)
                and min(a[2], b[2]) - max(a[0], b[0]) > 1.5
                and min(a[3], b[3]) - max(a[1], b[1]) > 1.5
                and 0.1 < intersection(a, b) / area(b) < 0.9
                for j, b in enumerate(boxes)
            )
        )
    parents = []
    for index, box in enumerate(boxes):
        choices = [
            (area(parent), n)
            for n, parent in enumerate(boxes)
            if n != index
            and can_parent[n]
            and area(parent) > area(box) + 1
            and inside(box, parent, 1.5)
            and (
                parent[2] - parent[0] > box[2] - box[0] + 1.5 or parent[3] - parent[1] > box[3] - box[1] + 1.5
            )
        ]
        parents.append(min(choices)[1] if choices else -1)
    tile_parent = set()
    for n, box in enumerate(boxes):
        children = [b for i, b in enumerate(boxes) if parents[i] == n]
        if len(children) >= 2:
            bounds = (
                min(b[0] for b in children),
                min(b[1] for b in children),
                max(b[2] for b in children),
                max(b[3] for b in children),
            )
            if max(abs(a - b) for a, b in zip(box, bounds)) <= 0.3:
                tile_parent.add(n)
    excluded = {
        n
        for n in tile_parent
        if not any(
            i != n and parents[i] == parents[n] and i not in tile_parent and adjacent(box, boxes[n])
            for i, box in enumerate(boxes)
        )
    }
    owner = list(range(len(boxes)))

    def find(n):
        while owner[n] != n:
            owner[n] = owner[owner[n]]
            n = owner[n]
        return n

    for i, box in enumerate(boxes):
        if i in excluded:
            continue
        for j in range(i):
            if j not in excluded and parents[i] == parents[j] and adjacent(box, boxes[j]):
                owner[find(i)] = find(j)
    groups: dict[int, list[Rect]] = {}
    for n, box in enumerate(boxes):
        if n not in excluded:
            groups.setdefault(find(n), []).append(box)
    grids = []
    for root, group in groups.items():
        is_container = root in parents
        parent = parents[root]
        parent_attachable = (
            parent >= 0
            and parent not in excluded
            and (len(groups.get(find(parent), [])) >= 2 or parent in parents)
        )
        only_child = parent >= 0 and parents.count(parent) == 1
        singleton = (
            len(group) == 1
            and (is_container or parent_attachable or only_child)
            and ruled_box(group[0], page.edges)
        )
        boundary_part = (
            len(group) == 1
            and (group[0][1] < page.height * 0.17 or group[0][3] > page.height * 0.83)
            and group[0][2] - group[0][0] >= 100
        )

        if len(group) >= 2 or (singleton or boundary_part) and strategy == "clip":
            if len(group) > options.max_cells:
                raise ParseError("RESOURCE_LIMIT", "Clipping cell budget exceeded")
            grid = PdfGrid(group, strategy)
            grid.boundary_part = boundary_part and not singleton
            grids.append(grid)
    return grids


def fill_grids(page, options: ParseOptions, chars: list[dict]) -> list[PdfGrid]:
    """Use tiled colored cell backgrounds; a page background alone is not a table."""
    rects = [
        r
        for r in page.rects
        if r.get("fill")
        and r["width"] >= 4
        and r["height"] >= 2
        and r["width"] * r["height"] < page.width * page.height * 0.75
    ]
    boxes = [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in rects]
    colored = [
        box
        for box, r in zip(boxes, rects)
        if r.get("non_stroking_color") not in (None, 1, (1, 1, 1), (1.0, 1.0, 1.0))
    ]
    grids = [
        grid
        for grid in rectangular_grids(boxes, page, options, "fill")
        if len(grid.cells) >= 3 and any(inside(box, grid.bbox) for box in colored)
    ]
    for grid in grids:
        # Repeated shaded value cells may have unshaded labels aligned beside them.
        cells = sorted(grid.cells, key=lambda b: b[1])
        if len(cells) < 3 or any(
            abs(b[0] - cells[0][0]) > 0.3 or abs(b[2] - cells[0][2]) > 0.3 for b in cells
        ):
            continue
        labels = [
            [
                c
                for c in chars
                if c["x1"] < box[0] - 2
                and box[1] <= (c["top"] + c["bottom"]) / 2 < box[3]
                and c["text"].strip()
            ]
            for box in cells
        ]
        if not all(labels):
            continue
        bounds = [(min(c["x0"] for c in row), max(c["x1"] for c in row)) for row in labels]
        aligned = (
            min(
                max(a for a, b in bounds) - min(a for a, b in bounds),
                max(b for a, b in bounds) - min(b for a, b in bounds),
                max((a + b) / 2 for a, b in bounds) - min((a + b) / 2 for a, b in bounds),
            )
            <= 8
        )
        if aligned:
            left = min(a for a, b in bounds)
            grid.__dict__.pop("bbox", None)
            grid.cells.extend((left, box[1], box[0], box[3]) for box in cells)
            grid.strategy = "fill"
    return grids
