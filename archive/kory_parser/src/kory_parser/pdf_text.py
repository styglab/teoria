"""PDF glyph deduplication and indexed cell text selection with stable source order."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from operator import itemgetter


def dedupe_glyphs(chars: list[dict], tolerance: float = 0.3) -> list[dict]:
    """Keep pdfplumber's transitive Y/X clusters without quadratic list.index calls.

    Equal glyph/font/size groups are clustered by adjacent Y coordinates, then X.
    The topmost, then leftmost glyph represents each cluster. Input order breaks
    ties and is restored with a linear pass over the retained input indices.
    """
    groups = defaultdict(list)
    for index, char in enumerate(chars):
        groups[(char["upright"], char["text"], char["fontname"], char["size"])].append(index)
    keep = bytearray(len(chars))
    for indices in groups.values():
        if len(indices) == 1:
            keep[indices[0]] = 1
            continue
        indices.sort(key=lambda i: chars[i]["doctop"])
        start = 0
        for end in range(1, len(indices) + 1):
            if (
                end < len(indices)
                and chars[indices[end]]["doctop"] <= chars[indices[end - 1]]["doctop"] + tolerance
            ):
                continue
            by_x = sorted(indices[start:end], key=lambda i: chars[i]["x0"])
            left = 0
            for right in range(1, len(by_x) + 1):
                if right < len(by_x) and chars[by_x[right]]["x0"] <= chars[by_x[right - 1]]["x0"] + tolerance:
                    continue
                chosen = min(by_x[left:right], key=lambda i: (chars[i]["doctop"], chars[i]["x0"], i))
                keep[chosen] = 1
                left = right
            start = end
    return [char for index, char in enumerate(chars) if keep[index]]


class CharacterIndex:
    """Select glyph centers in a cell using Y-range lookup, preserving input order."""

    def __init__(self, chars: list[dict]):
        self.items = sorted(
            ((c["top"] + c["bottom"]) / 2, i, (c["x0"] + c["x1"]) / 2, c) for i, c in enumerate(chars)
        )
        self.ys = [item[0] for item in self.items]

    def within(self, box, *, include_boundary=False) -> list[dict]:
        lo = bisect_left(self.ys, box[1])
        hi = (bisect_right if include_boundary else bisect_left)(self.ys, box[3])
        found = [
            item
            for item in self.items[lo:hi]
            if box[0] <= item[2] and (item[2] <= box[2] if include_boundary else item[2] < box[2])
        ]
        found.sort(key=itemgetter(1))
        return [item[3] for item in found]
