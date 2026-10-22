"""Recover logical paragraphs and list depth while preserving source line regions."""

import re
from collections import Counter, defaultdict
from dataclasses import replace

MARKER = re.compile(
    r"^(?P<marker>(?:\d{1,4}|[A-Za-z가-힣]|[ivxlcdmIVXLCDM]{1,8})[.)]|\(\d{1,4}\)|[①-⑳㉑-㉟]|[•●○◦▪▫‣⁃∙·*\-▸►])\s+(?P<body>\S)"
)
MONOSPACE = re.compile(r"mono|courier|typewriter|cmtt|cmtl", re.IGNORECASE)


def marker(text):
    found = MARKER.match(text)
    if found and found["marker"] == "-" and found["body"].isdigit():
        return None
    if (
        found
        and found["marker"] == "*"
        and (
            text[found.start("body")] == "="
            or re.match(r"[^:：]{1,40}[:：]\s*[_…\.]{3,}", text[found.start("body") :])
        )
    ):
        return None
    return found


def recover_paragraphs(blocks, typography):
    blocks = heading_lines(blocks, typography)
    left_edges = defaultdict(Counter)
    for block in blocks:
        if block.type == "paragraph" and block.source and block.source.bbox:
            left_edges[block.source.page][round(block.source.bbox[0], 1)] += 1
    result = []
    current = None
    last_line = None

    def flush():
        nonlocal current
        if current is not None:
            result.append(current)
        current = None

    def compatible(previous, following, initial, previous_style, next_style):
        if not previous_style or not next_style or not initial:
            return False
        if not previous_style.horizontal or not next_style.horizontal:
            return False
        if previous.source.page != following.source.page:
            return False
        a, b = previous.source.bbox, following.source.bbox
        size = previous_style.size
        if MONOSPACE.search(previous_style.font) or MONOSPACE.search(next_style.font):
            return False
        if (
            abs(size - next_style.size) > size * 0.12
            or abs(previous_style.bold_fraction - next_style.bold_fraction) > 0.5
        ):
            return False
        if not size * 0.65 <= b[1] - a[1] <= size * 1.85:
            return False
        if marker(following.text):
            return False
        initial_box = initial.source.bbox
        first_marker = marker(initial.text)
        if first_marker:
            # A wrapped item has a hanging indent. Another marker starts a new item.
            if not initial_box[0] + size * 0.6 <= b[0] <= initial_box[0] + size * 4:
                return False
        elif re.search(r"[.!?。！？][\"'”’）)]?$", previous.text) and any(
            count >= 3 and size * 0.6 <= b[0] - edge <= size * 3
            for edge, count in left_edges[following.source.page].items()
        ):
            # Native PDF blocks can contain several tightly spaced paragraphs.
            # A repeated body margin distinguishes a new first-line indent.
            return False
        elif abs(b[0] - a[0]) > size * 0.5 and (
            # Only a measured first-line indent may return to the block's left edge.
            previous_style.native_block != next_style.native_block
            or not size * 0.5 <= a[0] - b[0] <= size * 3
        ):
            return False
        same_native = (
            previous_style.native_block is not None and previous_style.native_block == next_style.native_block
        )
        if not same_native:
            # Separate engine blocks need positive continuation evidence.
            if re.search(r"[.!?。！？:：][\"'”’）)]?$", previous.text):
                return False
            if abs(a[2] - b[2]) > size * 2:
                return False
        return True

    initial = None
    for block in blocks:
        style = typography.style(block)
        if block.type != "paragraph" or not block.source or not block.source.bbox:
            flush()
            result.append(block)
            last_line, initial = None, None
            continue
        previous_style = typography.style(last_line) if last_line is not None else None
        if current is not None and compatible(last_line, block, initial, previous_style, style):
            if not current.regions:
                current.regions = [initial.source]
            current.regions.append(block.source)
            a, b = current.source.bbox, block.source.bbox
            current.source = replace(
                current.source, bbox=(min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
            )
            current.text += " " + block.text
        else:
            flush()
            current = replace(block, regions=list(block.regions))
            initial = block
        last_line = block
    flush()
    return list_levels(result)


def heading_lines(blocks, typography):
    result = []
    for block in blocks:
        previous = result[-1] if result else None
        before = typography.style(previous) if previous is not None else None
        after = typography.style(block)
        if (
            previous is not None
            and previous.type == block.type == "heading"
            and previous.level == block.level
            and before
            and after
            and previous.source.page == block.source.page
        ):
            a, b = previous.source.bbox, block.source.bbox
            same = (
                before.native_block is not None
                and before.native_block == after.native_block
                and abs(before.size - after.size) <= before.size * 0.05
            )
            if (
                same
                and 0.6 * before.size <= b[1] - a[1] <= 1.8 * before.size
                and abs(a[0] + a[2] - b[0] - b[2]) <= before.size * 4
            ):
                merged = replace(
                    previous,
                    text=previous.text + " " + block.text,
                    source=replace(
                        previous.source,
                        bbox=(min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])),
                    ),
                    regions=[*(previous.regions or [previous.source]), block.source],
                )
                result[-1] = merged
                typography.styles[(merged.source.page, merged.source.bbox, merged.text)] = before
                continue
        result.append(block)
    return result


def list_levels(blocks):
    indents, page, previous_top = [], None, None
    for block in blocks:
        found = marker(block.text) if block.type == "paragraph" else None
        if not found or not block.source or not block.source.bbox:
            indents = []
            continue
        if page != block.source.page or previous_top is not None and block.source.bbox[1] < previous_top:
            indents, page = [], block.source.page
        previous_top = block.source.bbox[1]
        position = block.source.bbox[0]
        while indents and position < indents[-1] - 4:
            indents.pop()
        if not indents or position > indents[-1] + 6:
            indents.append(position)
        block.type = "list"
        block.level = len(indents)
    return blocks
