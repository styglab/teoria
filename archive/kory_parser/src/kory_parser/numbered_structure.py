"""Recover a literal, indented HWPX numbering outline on explicit request.

Repeated Roman sections establish the root. Leading source whitespace establishes
child depth, with one marker family per active depth. Native metadata wins. Text,
spans and source references stay intact, including multiline paragraph contents;
only the first line's enumeration is represented, without splitting child lines.
"""

from __future__ import annotations

import re
import unicodedata
from itertools import pairwise

from .models import Block

ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
PREFIX = re.compile(r"(?P<mark>[Ⅰ-Ⅻⅰ-ⅻ]+\.|[IVX]{1,5}\.|[1-9]\d?[.)]|[가나다라마바사아자차카타파하][.)])(?=\s+\S)")
PAGE_LABEL = re.compile(r"\t\s*\d{1,4}\s*$")
INITIALS = frozenset("ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹⅺⅻIVX123456789가나다라마바사아자차카타파하")


def literal_label(block: Block):
    if not block.spans or block.inline_continuation or not block.text or block.text[0] not in INITIALS:
        return None
    if PAGE_LABEL.search(block.text[-32:]):
        return None  # printed contents entries describe pages, not body list scope
    # A bounded prefix avoids copying long paragraphs or embedded continuations.
    pieces = []
    remaining = 48
    for span in block.spans:
        pieces.append(span.text[:remaining])
        remaining -= len(pieces[-1])
        if remaining <= 0:
            break
    raw = "".join(pieces)
    stripped = raw.lstrip(" \t\u3000")
    found = PREFIX.match(stripped)
    if not found or not block.text.startswith(found["mark"]):
        return None
    mark = found["mark"]
    value = unicodedata.normalize("NFKC", mark[:-1]).upper()
    if value in ROMAN:
        family, ordinal = "roman", ROMAN.index(value) + 1
    elif value.isdigit():
        family, ordinal = "digit" + mark[-1], int(value)
    else:
        family, ordinal = "hangul" + mark[-1], ord(value[0])
    indent = len(raw[:len(raw) - len(stripped)].expandtabs(4))
    return indent, family, ordinal


def recover_run(blocks: list[Block]) -> None:
    # The root must be repeated in the source; an isolated Roman-looking phrase
    # or ordinary decimal list does not establish a document hierarchy.
    roots = []
    for index, block in enumerate(blocks):
        if block.text and block.text[0] in "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹⅺⅻIVX":
            item = literal_label(block)
            if item and item[1] == "roman":
                roots.append((index, item))
    # A contents row can omit its own page label while its child rows carry
    # tab-separated page numbers. Such rows must not establish body scope.
    roots = [(index, item) for index, item in roots
             if not any(PAGE_LABEL.search(b.text[-32:]) for b in blocks[index + 1:index + 5])]
    if len(roots) < 2:
        return
    root_indent = min(item[0] for _, item in roots)
    if not any(b[1][2] == a[1][2] + 1 for a, b in pairwise(roots)):
        return
    labels = [(i, item) for i, b in enumerate(blocks) if (item := literal_label(b))]
    if not any(item[0] > root_indent and item[1] != "roman" for _, item in labels):
        return
    root_positions = {index for index, _ in roots}
    stack = []
    last_index = None
    for index, (indent, family, _) in labels:
        if last_index is not None and index - last_index > 64:
            stack = []
        if family == "roman":
            if index not in root_positions:
                stack = []
                continue
            stack = [(indent, family)]
        elif stack and indent > stack[0][0]:
            while stack and stack[-1][0] > indent:
                stack.pop()
            if stack[-1][0] == indent:
                if stack[-1][1] != family:
                    continue  # same indentation with conflicting markers is ambiguous
            elif family not in {kind for _, kind in stack}:
                stack.append((indent, family))
            else:
                continue
        else:
            continue
        last_index = index
        blocks[index].type = "list"
        blocks[index].level = len(stack)


def recover_numbered_structure(blocks: list[Block]) -> None:
    run = []
    part = None
    for block in blocks:
        current = block.source.part if block.source else None
        if block.type in {"heading", "list", "separator"} or (part is not None and current != part):
            recover_run(run)
            run = []
        if block.type == "paragraph":
            run.append(block)
        part = current
        # Cells and children are separate scopes. Flat cell text is never split.
        if block.table:
            for row in block.table.cells:
                for cell in row:
                    if not cell.covered and cell.blocks:
                        recover_numbered_structure(cell.blocks)
        if block.children:
            recover_numbered_structure(block.children)
    recover_run(run)
