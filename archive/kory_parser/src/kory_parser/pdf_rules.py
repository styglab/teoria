"""Reconstruct ruled cells from measured line segments, with no PDF engine imports.

Edge snapping, intersections and smallest-cell rules adapted from
pdfplumber 0.11.10 (MIT). See third_party/pdfplumber_license.txt.
"""

from itertools import groupby

from .models import ParseError
from .pdf_geometry import PdfGrid, intersection
from .pdf_words import clusters


def edges_from_objects(objects):
    edges = []
    for line in objects.get("line", []):
        edges.append(dict(line, orientation="h" if line["top"] == line["bottom"] else "v"))
    for rect in objects.get("rect", []):
        edges.extend(
            [
                dict(rect, bottom=rect["top"], height=0, orientation="h"),
                dict(rect, top=rect["bottom"], height=0, orientation="h"),
                dict(rect, x1=rect["x0"], width=0, orientation="v"),
                dict(rect, x0=rect["x1"], width=0, orientation="v"),
            ]
        )
    return edges


def open_sided_boundaries(vertical, horizontal, existing_grids=()):
    """Infer open table sides from repeated row endpoints and an internal divider.

    Both ends of the divider must meet full-width row rules. Every crossing row
    must have the same endpoints; a lone separator, ragged rules or a divider
    extending into surrounding text does not establish a table boundary.
    """
    inferred = []
    for divider in vertical:
        rows = [
            rule
            for rule in horizontal
            if divider["top"] - 1 <= rule["top"] <= divider["bottom"] + 1
            # A border can sit just inside a horizontal stroke's end cap.
            # Use the visible-cell edge tolerance to exclude such outer rules.
            and rule["x0"] + 1.6 < divider["x0"] < rule["x1"] - 1.6
        ]
        if len(rows) < 3:
            continue
        rows.sort(key=lambda rule: rule["top"])
        left, right = rows[0]["x0"], rows[0]["x1"]
        if (
            abs(rows[0]["top"] - divider["top"]) > 1
            or abs(rows[-1]["top"] - divider["bottom"]) > 1
            or any(abs(row["x0"] - left) > 1 or abs(row["x1"] - right) > 1 for row in rows)
        ):
            continue
        bounds = (left, divider["top"], right, divider["bottom"])
        if any(intersection(bounds, grid.bbox) > 0 for grid in existing_grids):
            continue  # Keep already detected clipping/shading geometry authoritative.
        for position in (left, right):
            if any(
                left - 1 <= edge["x0"] <= right + 1
                and (edge["x0"] < divider["x0"] if position == left else edge["x0"] > divider["x0"])
                and edge["top"] <= divider["top"] + 1
                and edge["bottom"] >= divider["bottom"] - 1
                for edge in vertical + inferred
            ):
                continue
            inferred.append(dict(divider, x0=position, x1=position, width=0))
    return inferred


def paired_rule_groups(groups, axis):
    """Collapse isolated matching stroke pairs, preserving the normal 1pt snap.

    A pair must have matching segment extents and stroke style on both sides.
    Nearby rules belonging to different tables or a chain of narrow partitions
    do not establish a double border. Rectangles retain their original edges.
    """
    low, high = ("top", "bottom") if axis == "x0" else ("x0", "x1")
    positions = [sum(e[axis] for e in group) / len(group) for group in groups]

    def signatures(group):
        if any(e.get("object_type") != "line" or e[high] - e[low] < 4 for e in group):
            return None
        return {
            (e[low], e[high], round(e.get("linewidth", 0), 3), tuple(e.get("stroking_color") or ()))
            for e in group
        }

    def matches(left, right):
        return all(
            any(
                abs(a - c) <= 1.6 and abs(b - d) <= 1.6 and style == other_style
                for c, d, *other_style in right
            )
            for a, b, *style in left
        )

    index = 0
    while index < len(groups):
        if (
            index + 1 < len(groups)
            and positions[index + 1] - positions[index] <= 1.6
            and (index == 0 or positions[index] - positions[index - 1] > 1.6)
            and (index + 2 == len(groups) or positions[index + 2] - positions[index + 1] > 1.6)
        ):
            left, right = signatures(groups[index]), signatures(groups[index + 1])
            if left and right and matches(left, right) and matches(right, left):
                yield (groups[index], groups[index + 1]), (positions[index] + positions[index + 1]) / 2
                index += 2
                continue
        yield (groups[index],), positions[index]
        index += 1


def corroborated_rule_pairs(grouped, vertical_edges):
    """Require a bounded internal divider crossing repeated double row rules.

    Decorative frames and lone header separators keep their original geometry.
    Once a grid is confirmed, connected outer stroke pairs belong to that grid.
    """
    pairs = {
        axis: {i: item for i, item in enumerate(items) if len(item[0]) == 2}
        for axis, items in grouped.items()
    }

    def crosses(vertical, horizontal):
        vg, x = vertical
        hg, y = horizontal
        return any(e["top"] - 1.6 <= y <= e["bottom"] + 1.6 for group in vg for e in group) and any(
            e["x0"] - 1.6 <= x <= e["x1"] + 1.6 for group in hg for e in group
        )

    links = {i: {j for j, h in pairs["h"].items() if crosses(v, h)} for i, v in pairs["v"].items()}
    confirmed = {"v": set(), "h": set()}
    for index, (parents, position) in pairs["v"].items():
        if len(links[index]) < 2:
            continue
        top = min(e["top"] for group in parents for e in group)
        bottom = max(e["bottom"] for group in parents for e in group)
        bounds = [e["x0"] for e in vertical_edges if e["top"] <= top + 1.6 and e["bottom"] >= bottom - 1.6]
        if any(x < position - 1.6 for x in bounds) and any(x > position + 1.6 for x in bounds):
            confirmed["v"].add(index)
            confirmed["h"].update(links[index])
    changed = True
    while changed:
        changed = False
        for index, neighbors in links.items():
            if index not in confirmed["v"] and neighbors & confirmed["h"]:
                confirmed["v"].add(index)
                confirmed["h"].update(neighbors)
                changed = True
    return confirmed


def ruled_grids(edges, options, existing_grids=()):
    grouped = {}
    originals = {}
    for orientation, axis in (("v", "x0"), ("h", "top")):
        own = [
            e
            for e in edges
            if e.get("orientation") == orientation
            and e.get("width" if orientation == "h" else "height", 0) >= 1
        ]
        originals[orientation] = own
        grouped[orientation] = list(paired_rule_groups(clusters(own, lambda e, axis=axis: e[axis], 1), axis))
    confirmed = corroborated_rule_pairs(grouped, originals["v"])
    snapped = []
    for orientation, axis in (("v", "x0"), ("h", "top")):
        for index, (parents, position) in enumerate(grouped[orientation]):
            # A single decorative double rule is insufficient evidence of a
            # double-bordered grid. Preserve its ordinary per-group snapping.
            if len(parents) == 2 and index not in confirmed[orientation]:
                choices = [(group, sum(e[axis] for e in group) / len(group)) for group in parents]
            else:
                choices = [([edge for group in parents for edge in group], position)]
            for group, coordinate in choices:
                for edge in group:
                    snapped.append(
                        dict(
                            edge,
                            **(
                                {"x0": coordinate, "x1": coordinate}
                                if orientation == "v"
                                else {"top": coordinate, "bottom": coordinate}
                            ),
                        )
                    )
    group_key = lambda e: (e["orientation"], e["top"] if e["orientation"] == "h" else e["x0"])
    joined = []
    for (direction, _), group in groupby(sorted(snapped, key=group_key), key=group_key):
        low, high = ("x0", "x1") if direction == "h" else ("top", "bottom")
        current = None
        for edge in sorted(group, key=lambda e: e[low]):
            if current is not None and edge[low] <= current[high] + 1:
                current[high] = max(current[high], edge[high])
            else:
                current = dict(edge)
                joined.append(current)
    vertical = [e for e in joined if e["orientation"] == "v" and e["bottom"] - e["top"] >= 1]
    horizontal = [e for e in joined if e["orientation"] == "h" and e["x1"] - e["x0"] >= 1]
    vertical.extend(open_sided_boundaries(vertical, horizontal, existing_grids))
    points = {}
    for vi, v in enumerate(sorted(vertical, key=lambda e: (e["x0"], e["top"]))):
        for hi, h in enumerate(sorted(horizontal, key=lambda e: (e["top"], e["x0"]))):
            if v["top"] - 1 <= h["top"] <= v["bottom"] + 1 and h["x0"] - 1 <= v["x0"] <= h["x1"] + 1:
                point = points.setdefault((v["x0"], h["top"]), {"v": set(), "h": set()})
                point["v"].add(vi)
                point["h"].add(hi)
                if len(points) > options.max_cells * 4:
                    raise ParseError("RESOURCE_LIMIT", "PDF intersection budget exceeded")

    def connects(a, b):
        return (a[0] == b[0] and bool(points[a]["v"] & points[b]["v"])) or (
            a[1] == b[1] and bool(points[a]["h"] & points[b]["h"])
        )

    cells = []
    ordered = sorted(points)
    for index, point in enumerate(ordered):
        below = [p for p in ordered[index + 1 :] if p[0] == point[0]]
        right = [p for p in ordered[index + 1 :] if p[1] == point[1]]
        found = False
        for lower in below:
            if not connects(point, lower):
                continue
            for next_right in right:
                corner = (next_right[0], lower[1])
                if (
                    connects(point, next_right)
                    and corner in points
                    and connects(corner, lower)
                    and connects(corner, next_right)
                ):
                    cells.append((*point, *corner))
                    found = True
                    break
            if found:
                break
        if len(cells) > options.max_cells:
            raise ParseError("RESOURCE_LIMIT", "PDF ruled cell budget exceeded")
    owners = list(range(len(cells)))

    def owner(i):
        while owners[i] != i:
            owners[i] = owners[owners[i]]
            i = owners[i]
        return i

    corners = {}
    for i, (x0, top, x1, bottom) in enumerate(cells):
        for corner in ((x0, top), (x0, bottom), (x1, top), (x1, bottom)):
            if corner in corners:
                owners[owner(i)] = owner(corners[corner])
            corners[corner] = i
    tables = {}
    for i, cell in enumerate(cells):
        tables.setdefault(owner(i), []).append(cell)
    return [
        PdfGrid(group, "line")
        for group in sorted(tables.values(), key=lambda g: min((c[1], c[0]) for c in g))
        if len(group) > 1
    ]
