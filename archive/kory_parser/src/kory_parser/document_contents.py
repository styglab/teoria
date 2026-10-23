"""Read explicit contents sections without rewriting document text or table cells.

PDF callers supply physical lines before paragraph joining. Office/Hangul callers
supply native paragraphs and rows. Printed labels never become physical pages
without a matching body heading. Uncertain targets remain unresolved.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace

from .models import ContentsEntry, DocumentContents, SourceRef

CONTENTS_TITLE = re.compile(
    r"^[\s<〈《【\[]*(?:목\s*차|차\s*례|(?:table\s+of\s+|short\s+)?contents)[\s>〉》】\]]*$", re.IGNORECASE
)
NUMBER = (
    r"(?:Appendix\s+[A-Z]|제\s*\d+\s*[장절편부]|\d+(?:\.\d+)*|[A-Z](?:\.\d+)+|[Ⅰ-Ⅻⅰ-ⅻIVXLCDMivxlcdm]+|[A-Z])"
)
PREFIX = re.compile(rf"^(?P<number>{NUMBER}[.)]?)(?:\s+|(?<=[장절편부]))(?P<title>\S.*)$")
NUMBER_ONLY = re.compile(rf"^{NUMBER}[.)]?$")
PAGE = re.compile(r"^(?P<title>.*?)\s+(?P<page>\d{1,4}|[ivxlcdm]{1,8})\s*$")
LEADER = re.compile(r"(?:[.·․…⋯]\s*){3,}")
PROPOSAL_FORM = re.compile(
    r"제안서\s*(?:작성\s*)?(?:서식|양식)|proposal\s+(?:submission\s+)?template", re.IGNORECASE
)


@dataclass(frozen=True)
class ContentsLine:
    text: str
    source: SourceRef | None
    regions: tuple[SourceRef, ...] = ()
    kind: str = "paragraph"
    page_label_hint: bool | None = None


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def merged_source(regions):
    if not regions:
        return None
    first = regions[0]
    if all(r.bbox and r.page == first.page and r.part == first.part for r in regions):
        return replace(
            first,
            bbox=(
                min(r.bbox[0] for r in regions),
                min(r.bbox[1] for r in regions),
                max(r.bbox[2] for r in regions),
                max(r.bbox[3] for r in regions),
            ),
        )
    return first


def document_lines(blocks):
    """Keep row fields together and preserve original cell/paragraph anchors."""
    for block in blocks:
        if block.table:
            for row in block.table.cells:
                cells = [cell for cell in row if not cell.covered]
                # Cells in a row encode number, title and page label together.
                lines = [cell.text.splitlines() or [""] for cell in cells]
                regions = tuple(cell.source for cell in cells if cell.source)
                for index in range(max((len(parts) for parts in lines), default=0)):
                    text = " ".join(parts[index] for parts in lines if index < len(parts)).strip()
                    if text:
                        yield ContentsLine(
                            text,
                            merged_source(regions),
                            regions,
                            "table_row",
                            True if len(cells) > 1 and cells[-1].text.strip().isdigit() else None,
                        )
                for cell in cells:
                    if any(child.table for child in cell.blocks):
                        yield from document_lines([child for child in cell.blocks if child.table])
        elif block.text.strip():
            for text in block.text.splitlines():
                if text.strip():
                    yield ContentsLine(
                        text.strip(), block.source, (block.source,) if block.source else (), block.type
                    )
        yield from document_lines(block.children)


def adjacent(before, after):
    a, b = before.source, after.source
    if not a or not b or a.part != b.part or a.page != b.page:
        return False
    if not a.bbox or not b.bbox:
        return True
    height = max(1, a.bbox[3] - a.bbox[1])
    return -height <= b.bbox[1] - a.bbox[1] <= height * 2.2


def combine_fragments(lines):
    """A separate section number belongs to the next short adjacent title."""
    result = []
    for line in lines:
        if (
            result
            and NUMBER_ONLY.fullmatch(result[-1].text)
            and (result[-1].text.endswith((".", ")")) or result[-1].text.isupper())
            and adjacent(result[-1], line)
        ):
            before = result[-1]
            if len(line.text) <= 180 and not NUMBER_ONLY.fullmatch(line.text):
                regions = before.regions + line.regions
                result[-1] = ContentsLine(
                    before.text + " " + line.text,
                    merged_source(regions),
                    regions,
                    line.kind,
                    line.page_label_hint,
                )
                continue
        result.append(line)
    return result


def entry_parts(line):
    text = LEADER.sub(" ", line.text).strip()
    found = PREFIX.match(text)
    if found:
        number, title = found["number"], found["title"].lstrip(". ")
    else:
        number, title = None, text
    label = PAGE.match(title) if line.page_label_hint is not False else None
    if label:
        title, page = label["title"].strip(), label["page"]
    else:
        page = None
    if not title or len(title) > 180:
        return None
    # Unnumbered headings are admitted only inside an explicit contents section.
    if not number and not page and line.kind != "heading":
        return None
    if re.search(r"[。!?！？]$", title) or not any(c.isalpha() for c in title):
        return None
    return number, title, page


def hierarchy(number, has_sections, previous=None):
    if not number:
        return None
    token = unicodedata.normalize("NFKC", number).rstrip(".)")
    if token.startswith("Appendix"):
        return 1
    if re.fullmatch(r"[A-Z](?:\.\d+)+", token):
        return token.count(".") + 1
    if section_number(number, previous):
        return 1
    if token[0].isdigit():
        return token.count(".") + 1 + int(has_sections)
    return 2 if has_sections else 1


def section_number(number, previous=None):
    token = unicodedata.normalize("NFKC", number or "").rstrip(".)")
    before = unicodedata.normalize("NFKC", previous or "").rstrip(".)")
    if len(token) == len(before) == 1 and before.isalpha() and ord(token) == ord(before) + 1:
        return False
    return bool(token.startswith("제") or re.fullmatch(r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)", token))


def contents_window(lines, start, parts_at):
    entries, seen = [], set()
    section = ""
    previous_number = None
    index, misses, paged = start + 1, 0, 0
    for index in range(start + 1, min(len(lines), start + 1201)):
        line = lines[index]
        if CONTENTS_TITLE.fullmatch(line.text):
            break
        if (
            lines[start].source
            and line.source
            and lines[start].source.page
            and line.source.page
            and line.source.page > lines[start].source.page + 32
        ):
            break
        parsed = parts_at(index)
        if len(entries) >= 2 and paged >= len(entries) * 0.6 and (not parsed or not parsed[2]):
            following = [parts_at(i) for i in range(index, min(index + 4, len(lines)))]
            if not any(parts and parts[2] for parts in following) and not re.fullmatch(
                r"[-–—\s\divxlcdm]+", line.text, re.IGNORECASE
            ):
                break
        if (
            parsed
            and parsed[0] is None
            and parsed[2]
            and entries
            and not entries[-1][1][2]
            and adjacent(entries[-1][0], line)
        ):
            previous, (number, title, _) = entries[-1]
            before, after = previous.source, line.source
            if before and after and before.bbox and after.bbox and after.bbox[0] >= before.bbox[0] + 3:
                regions = previous.regions + line.regions
                entries[-1] = (
                    ContentsLine(
                        previous.text + " " + line.text, merged_source(regions), regions, previous.kind
                    ),
                    (number, title + " " + parsed[1], parsed[2]),
                )
                paged += 1
                continue
        if parsed is None:
            if len(line.text) > 100:
                misses += 1
                if misses >= 2:
                    break
            # A wrapped title ending in a page label belongs to its previous item.
            if entries and not entries[-1][1][2] and adjacent(entries[-1][0], line):
                label = PAGE.match(LEADER.sub(" ", line.text).strip())
                if label and not PREFIX.match(line.text):
                    previous, (number, title, _) = entries[-1]
                    regions = previous.regions + line.regions
                    entries[-1] = (
                        ContentsLine(
                            previous.text + " " + line.text, merged_source(regions), regions, previous.kind
                        ),
                        (number, title + " " + label["title"].strip(), label["page"]),
                    )
                    paged += 1
            continue
        if section_number(parsed[0], previous_number):
            section = normalized(parsed[0] or "")
        if parsed[0]:
            previous_number = parsed[0]
        key = (section, normalized(parsed[0] or ""), normalized(parsed[1]))
        if key in seen:
            if parsed[0]:
                break
            continue
        if entries and misses:
            break
        seen.add(key)
        entries.append((line, parsed))
        paged += bool(parsed[2])
    else:
        index += 1
    return entries, index


def recover_contents(blocks, page_sizes=None, page_labels=None):
    # Most documents have no contents title; avoid materializing all their rows.
    lines = []
    iterator = document_lines(blocks)
    for line in iterator:
        lines.append(line)
        if CONTENTS_TITLE.fullmatch(line.text):
            lines.extend(iterator)
            if page_labels is not None:
                lines = [
                    replace(
                        line, page_label_hint=(line.source.page, line.source.bbox, line.text) in page_labels
                    )
                    if line.source and line.kind != "table_row"
                    else line
                    for line in lines
                ]
            lines = combine_fragments(lines)
            break
    else:
        return []
    if page_sizes:
        margins = defaultdict(set)

        def margin_key(line):
            ref = line.source
            if not ref or not ref.bbox or ref.page not in page_sizes:
                return None
            height = page_sizes[ref.page][1]
            if ref.bbox[3] < height * 0.1 or ref.bbox[1] > height * 0.9:
                return re.sub(r"\d+", "", normalized(line.text))
            return None

        keys = [margin_key(line) for line in lines]
        for line, key in zip(lines, keys):
            if key:
                margins[key].add(line.source.page)
        lines = [line for line, key in zip(lines, keys) if len(margins.get(key, ())) < 2]
    parsed_lines = {}

    def parts_at(index):
        if index not in parsed_lines:
            parsed_lines[index] = entry_parts(lines[index])
        return parsed_lines[index]

    sections = []
    windows = []
    proposal_forms = []
    for start, line in enumerate(lines):
        if not CONTENTS_TITLE.fullmatch(line.text):
            continue
        items, end = contents_window(lines, start, parts_at)
        if len(items) < 2 or not any(parts[0] for _, parts in items):
            continue
        has_sections = any(section_number(number) for _, (number, _, _) in items)
        contents = DocumentContents(line.text, line.source)
        stack = []
        previous_number = None
        for source_line, (number, title, page) in items:
            level = hierarchy(number, has_sections, previous_number)
            if number:
                previous_number = number
            while stack and (level is None or stack[-1].level >= level):
                stack.pop()
            entry = ContentsEntry(
                f"contents_{len(sections) + 1}_entry_{len(contents.entries) + 1}",
                title,
                number,
                level,
                stack[-1].entry_id if stack and level == stack[-1].level + 1 else None,
                page,
                source_line.source,
                list(source_line.regions),
            )
            contents.entries.append(entry)
            if level is not None:
                stack.append(entry)
        sections.append(contents)
        windows.append((start, end))
        proposal_forms.append(
            any(PROPOSAL_FORM.search(previous.text) for previous in lines[max(0, start - 40) : start])
        )
    if not sections:
        return []
    body = defaultdict(list)
    excluded = {i for start, end in windows for i in range(start, end)}
    for index, line in enumerate(lines):
        if index in excluded:
            continue
        parts = parts_at(index)
        if parts and (parts[0] or line.kind == "heading"):
            number, title, _ = parts
            body[(normalized(number or ""), normalized(title))].append(line.source)
    for section in sections:
        for entry in section.entries:
            targets = body.get((normalized(entry.number or ""), normalized(entry.title)), [])
            targets = list(dict.fromkeys(target for target in targets if target))
            if len(targets) == 1:
                entry.target, entry.target_status = targets[0], "resolved"
            elif targets:
                entry.target_status = "ambiguous"
    # A required proposal outline is not this document's own navigation. Keep
    # real proposal TOCs when page labels or matching body headings support them.
    return [
        section
        for section, form in zip(sections, proposal_forms)
        if not form
        or any(entry.printed_page_label or entry.target_status != "unresolved" for entry in section.entries)
    ]
