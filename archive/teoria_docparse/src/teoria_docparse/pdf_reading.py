"""Geometry-only column discovery and reading order, independent of document topic."""

from collections import defaultdict
from statistics import median


def gutter(boxes, size=10):
    """Require substantial text on both sides of a shared vertical whitespace strip."""
    if len(boxes) < 6:
        return None
    left, right = min(b[0] for b in boxes), max(b[2] for b in boxes)
    width = right - left
    if width < size * 16:
        return None
    substantial = [b for b in boxes if b[2] - b[0] >= width * 0.15]
    best = None
    for step in range(12, 53):
        cut = left + width * step / 64
        before = [b for b in substantial if b[2] <= cut]
        after = [b for b in substantial if b[0] >= cut]
        if min(len(before), len(after)) < 3:
            continue
        lo, hi = max(b[2] for b in before), min(b[0] for b in after)
        if hi - lo < size * 1.2:
            continue
        overlap = min(max(b[3] for b in before), max(b[3] for b in after)) - max(
            min(b[1] for b in before), min(b[1] for b in after)
        )
        if overlap < size * 3:
            continue
        shared_top = max(min(b[1] for b in before), min(b[1] for b in after))
        shared_bottom = min(max(b[3] for b in before), max(b[3] for b in after))
        crossings = [
            b
            for b in substantial
            if b[0] < cut < b[2] and b[2] - b[0] < width * 0.65 and b[1] < shared_bottom and b[3] > shared_top
        ]
        if len(crossings) > max(2, (len(before) + len(after)) * 0.12):
            continue
        balance = min(len(before), len(after)) / max(len(before), len(after))
        score = (len(before) + len(after)) * balance + min(hi - lo, size * 6) / size
        candidate = (score, -(hi - lo), (lo + hi) / 2)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def column_positions(chars):
    """Discover multiple gutters from native line runs before table interpretation."""
    native = defaultdict(list)
    for char in chars:
        if "native_line" in char:
            native[char["native_line"]].append(char)
    boxes = [
        (
            min(c["x0"] for c in group),
            min(c["top"] for c in group),
            max(c["x1"] for c in group),
            max(c["bottom"] for c in group),
        )
        for group in native.values()
    ]
    size = median(c["size"] for c in chars) if chars else 10

    def discover(rectangles, depth=0):
        cut = gutter(rectangles, size)
        if cut is None or depth >= 4:
            return []
        return [
            *discover([b for b in rectangles if b[2] <= cut], depth + 1),
            cut,
            *discover([b for b in rectangles if b[0] >= cut], depth + 1),
        ]

    return discover(boxes)


def split_column_lines(lines, chars, cuts=None):
    """Split aligned lines only when native line runs support separate columns."""
    for cut in column_positions(chars) if cuts is None else cuts:
        result = []
        for line in lines:
            before = [w for w in line if (w["x0"] + w["x1"]) / 2 < cut]
            after = [w for w in line if (w["x0"] + w["x1"]) / 2 >= cut]
            ids = lambda words: {c.get("native_line") for w in words for c in w["chars"]}
            if before and after and not ids(before) & ids(after):
                result.extend([before, after])
            else:
                result.append(line)
        lines = result
    return lines


def reading_order(blocks, page_sizes):
    """Read each column to its end, respecting intervening full-width elements."""
    pages, unlocated = defaultdict(list), []
    for block in blocks:
        if block.source and block.source.bbox and block.source.page:
            pages[block.source.page].append(block)
        else:
            unlocated.append(block)

    def arrange(items, depth=0):
        ordered = sorted(items, key=lambda b: (b.source.bbox[1], b.source.bbox[0]))
        if depth >= 8:
            return ordered
        text = [b.source.bbox for b in items if b.type in ("paragraph", "heading", "list")]
        size = median(b[3] - b[1] for b in text) if text else 10
        cut = gutter(text, max(3, size * 0.75))
        if cut is None:
            return ordered
        spanners = [b for b in ordered if b.source.bbox[0] < cut < b.source.bbox[2]]
        if not spanners:
            return arrange([b for b in items if b.source.bbox[2] <= cut], depth + 1) + arrange(
                [b for b in items if b.source.bbox[0] >= cut], depth + 1
            )
        spanner_ids = {id(b) for b in spanners}
        remaining = [b for b in ordered if id(b) not in spanner_ids]
        result = []
        for block in spanners:
            top = block.source.bbox[1]
            preceding = [b for b in remaining if b.source.bbox[3] <= top + 0.5]
            result.extend(arrange(preceding, depth + 1))
            preceding_ids = {id(b) for b in preceding}
            remaining = [b for b in remaining if id(b) not in preceding_ids]
            # An overlapping side object prevents a reliable full-width cut.
            if any(b.source.bbox[1] < block.source.bbox[3] and b.source.bbox[3] > top for b in remaining):
                return ordered
            result.append(block)
        return result + arrange(remaining, depth + 1)

    result = []
    for page, items in sorted(pages.items()):
        width, height = page_sizes[page]
        backgrounds = [
            b
            for b in items
            if b.type == "image"
            and (b.source.bbox[2] - b.source.bbox[0]) * (b.source.bbox[3] - b.source.bbox[1])
            > width * height * 0.7
        ]
        result.extend(backgrounds)
        background_ids = {id(b) for b in backgrounds}
        result.extend(arrange([b for b in items if id(b) not in background_ids]))
    return result + unlocated
