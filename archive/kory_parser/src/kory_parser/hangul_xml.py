"""HWPX/HWPML native XML parsing with addressed cells and current-text revision policy."""

from __future__ import annotations

import base64
import posixpath
import re

from .document_io import DocumentZip, local_name, xml
from .hwp_numbering import format_number
from .models import (
    Block,
    Cell,
    Diagnostic,
    ParseError,
    ParseOptions,
    ParseResult,
    SourceRef,
    Span,
    plain_text,
    table_from_cells,
)


def attr(node, key: str, default: str = "") -> str:
    lowered = key.lower()
    for name, value in node.attrib.items():
        if (name == key and "}" not in key) or local_name(name).lower() == lowered:
            return value
    return default


def children_named(node, name: str):
    return [c for c in node if local_name(c.tag).lower() == name.lower()]


def first(node, name: str):
    lowered = name.lower()
    for child in node.iter():
        if (child.tag == name and "}" not in name) or local_name(child.tag).lower() == lowered:
            return child
    return None


class HangulXmlParser:
    def __init__(self, options: ParseOptions, result: ParseResult, archive: DocumentZip | None = None):
        self.options, self.result, self.archive = options, result, archive
        self.styles: dict[str, dict] = {}
        self.para_styles: dict[str, tuple[str, int, str]] = {}
        self.bullets: dict[str, str] = {}
        self.numberings: dict[str, dict[int, tuple[str, str, int]]] = {}
        self.number_counters: dict[str, list[int]] = {}
        self.outline_id = "1"
        self.images: dict[str, str] = {}
        self.part = ""
        self.section = 1
        self.deleted: set[int] = set()
        self.visible_text: dict[int, str] = {}
        self.visible_tail: dict[int, str] = {}

    def header(self, root) -> None:
        for node in root.iter():
            name = local_name(node.tag).lower()
            if name == "charpr":
                self.styles[attr(node, "id")] = {
                    "bold": first(node, "bold") is not None,
                    "italic": first(node, "italic") is not None,
                    "underline": any(
                        attr(n, "type").upper() not in ("", "NONE")
                        for n in node.iter()
                        if local_name(n.tag).lower() == "underline"
                    ),
                    "script": "sup"
                    if first(node, "supscript") is not None
                    else "sub"
                    if first(node, "subscript") is not None
                    else None,
                }
            elif name == "parapr":
                heading = first(node, "heading")
                if heading is not None:
                    self.para_styles[attr(node, "id")] = (
                        attr(heading, "type"),
                        int(attr(heading, "level", "0")) + 1,
                        attr(heading, "idRef"),
                    )
            elif name == "bullet":
                self.bullets[attr(node, "id")] = attr(node, "char")
            elif name == "numbering":
                self.numberings[attr(node, "id")] = {
                    int(attr(head, "level", "1")): (
                        (head.text or "").strip(),
                        attr(head, "numFormat", "DIGIT"),
                        int(attr(head, "start", "1")),
                    )
                    for head in node
                    if local_name(head.tag).lower() == "parahead"
                }
            elif name == "item" and attr(node, "href"):
                self.images[attr(node, "id")] = posixpath.normpath(
                    posixpath.join("Contents", attr(node, "href"))
                )

    def mark_deletions(self, root) -> None:
        """Markers can surround paragraphs/objects, not only text runs."""
        active: set[str] = set()

        def visit(node):
            name = local_name(node.tag).lower()
            if name == "deletebegin":
                active.add(attr(node, "id", "default"))
            elif name == "deleteend":
                active.discard(attr(node, "id", "default"))
            elif active and name in ("tbl", "table", "pic", "picture"):
                self.deleted.add(id(node))
            self.visible_text[id(node)] = (node.text or "") if not active else ""
            for child in node:
                visit(child)
                self.visible_tail[id(child)] = (child.tail or "") if not active else ""

        visit(root)
        if active:
            self.result.warnings.append(Diagnostic("MALFORMED_REVISION", "Unclosed deletion marker"))

    def ref(self, node, suffix: str = "") -> SourceRef:
        return SourceRef(self.part, f"{local_name(node.tag)}:{attr(node, 'id')}{suffix}")

    def walk(self, node, depth: int = 0) -> list[Block]:
        if depth > self.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "Document nesting exceeds budget")
        out = []
        for child in node:
            if id(child) in self.deleted:
                continue
            name = local_name(child.tag).lower()
            if name == "p":
                out.extend(self.paragraph(child, depth + 1))
            elif name in ("tbl", "table"):
                out.append(self.table(child, depth + 1))
            elif name in ("pic", "picture"):
                out.append(self.picture(child))
            elif name not in ("hiddencomment", "script", "secpr", "linesegarray", "parameters"):
                out.extend(self.walk(child, depth + 1))
        return out

    def paragraph(self, node, depth: int) -> list[Block]:
        out: list[Block] = []
        spans: list[Span] = []
        text: list[str] = []
        had_object = False
        heading, level, number_id = self.para_styles.get(attr(node, "paraPrIDRef"), ("", 1, ""))
        prefix = ""
        if heading == "BULLET":
            prefix = self.bullets.get(number_id, "")
        elif heading in ("NUMBER", "OUTLINE"):
            number_id = self.outline_id if heading == "OUTLINE" else number_id
            definition = self.numberings.get(number_id)
            if definition:
                counters = self.number_counters.setdefault(number_id, [-1] * 11)
                fmt, _, start = definition.get(level, (f"^{level}.", "DIGIT", 1))
                counters[level] = counters[level] + 1 if counters[level] >= 0 else start
                counters[level + 1 :] = [-1] * (10 - level)

                def replace(match):
                    ref = int(match[1])
                    _, kind, ref_start = definition.get(ref, ("", "DIGIT", 1))
                    return format_number(counters[ref] if counters[ref] >= 0 else ref_start, kind)

                prefix = re.sub(r"\^(?![^\W_])", "", re.sub(r"\^(10|[1-9])", replace, fmt)).strip()

        def flush() -> None:
            nonlocal spans, text, prefix
            value = "".join(text)
            if value.strip():
                kind = "heading" if heading == "OUTLINE" else "paragraph"
                if prefix:
                    value = prefix + " " + value.lstrip()
                    prefix = ""
                out.append(
                    Block(
                        kind,
                        value.strip(),
                        level=level if kind == "heading" else None,
                        source=self.ref(node),
                        spans=spans,
                    )
                )
            spans, text = [], []

        def visit(current, style: dict) -> None:
            nonlocal had_object
            if id(current) in self.deleted:
                return
            name = local_name(current.tag).lower()
            if name in ("tbl", "table"):
                flush()
                out.append(self.table(current, depth + 1))
                had_object = True
                return
            if name in ("pic", "picture"):
                flush()
                out.append(self.picture(current))
                had_object = True
                return
            if name == "p" and current is not node:
                flush()
                out.extend(self.paragraph(current, depth + 1))
                return
            if name in ("hiddencomment", "parameters", "script", "linesegarray", "secpr"):
                return
            if name == "run":
                style = self.styles.get(attr(current, "charPrIDRef"), {})
            if name in ("t", "char"):
                value = self.visible_text.get(id(current), current.text or "")
                if value:
                    text.append(value)
                    spans.append(Span(value, **style))
            if name in ("linebreak", "br", "tab", "nbspace", "fwspace"):
                value = "\n" if name in ("linebreak", "br") else "\t" if name == "tab" else " "
                text.append(value)
                spans.append(Span(value, **style))
            if name in ("equation",):
                script = first(current, "script")
                if script is not None and script.text:
                    text.append(script.text)
                    self.result.warnings.append(
                        Diagnostic(
                            "FORMULA_SOURCE_ONLY",
                            "HULK formula retained as source, not converted to LaTeX",
                            self.ref(current),
                        )
                    )
                return
            for child in current:
                visit(child, style)
                if name in ("t", "char"):
                    tail = self.visible_tail.get(id(child), child.tail or "")
                    if tail:
                        text.append(tail)
                        spans.append(Span(tail, **style))

        visit(node, {})
        flush()
        if not out and not had_object and self.options.keep_empty_paragraphs:
            out.append(Block("paragraph", source=self.ref(node)))
        return out

    def table(self, node, depth: int) -> Block:
        if depth > self.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "Table nesting exceeds budget")
        addressed = []
        rows = int(attr(node, "rowCnt", attr(node, "RowCount", "0")))
        cols = int(attr(node, "colCnt", attr(node, "ColCount", "0")))
        row_nodes = children_named(node, "tr") or children_named(node, "row")
        for row_index, row in enumerate(row_nodes):
            col_index = 0
            for cell_node in children_named(row, "tc") + children_named(row, "cell"):
                address = next(iter(children_named(cell_node, "cellAddr")), None)
                span = next(iter(children_named(cell_node, "cellSpan")), None)
                r = (
                    int(attr(address, "rowAddr", str(row_index)))
                    if address is not None
                    else int(attr(cell_node, "RowAddr", str(row_index)))
                )
                c = (
                    int(attr(address, "colAddr", str(col_index)))
                    if address is not None
                    else int(attr(cell_node, "ColAddr", str(col_index)))
                )
                rs = (
                    int(attr(span, "rowSpan", "1"))
                    if span is not None
                    else int(attr(cell_node, "RowSpan", "1"))
                )
                cs = (
                    int(attr(span, "colSpan", "1"))
                    if span is not None
                    else int(attr(cell_node, "ColSpan", "1"))
                )
                body = self.walk(cell_node, depth + 1)
                cell = Cell(
                    plain_text(body),
                    rs,
                    cs,
                    body if any(b.type in ("table", "image") for b in body) else [],
                    self.ref(node, f"/cell[{r},{c}]"),
                    attr(cell_node, "header") == "1",
                )
                addressed.append((r, c, cell))
                rows, cols = max(rows, r + rs), max(cols, c + cs)
                col_index = c + cs
        table = table_from_cells(rows, cols, addressed, self.options, attr(node, "id") or None)
        caption = next((c for c in node if local_name(c.tag).lower() == "caption"), None)
        if caption is not None:
            table.caption = plain_text(self.walk(caption, depth + 1))
        return Block("table", table=table, source=self.ref(node))

    def picture(self, node) -> Block:
        image = first(node, "img")
        key = attr(image, "binaryItemIDRef") if image is not None else attr(node, "BinItem")
        ref = SourceRef(self.part, key or attr(node, "id"))
        block = Block("image", source=ref)
        path = self.images.get(key)
        if self.options.images and path and self.archive and path in self.archive.names:
            block.image_data = base64.b64encode(self.archive.read(path)).decode("ascii")
            block.mime_type = "image/" + path.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
        self.result.warnings.append(
            Diagnostic("UNEXTRACTED_IMAGE_TEXT", "Image region requires OCR review", ref)
        )
        return block


def parse_hwpx(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "hwpx", page_mode="section")
    with DocumentZip(data, options) as archive:
        parser = HangulXmlParser(options, result, archive)
        if "Contents/header.xml" in archive.names:
            parser.header(archive.xml("Contents/header.xml"))
        sections = sorted(
            (n for n in archive.names if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)),
        )
        if "Contents/content.hpf" in archive.names:
            manifest = archive.xml("Contents/content.hpf")
            parser.header(manifest)
            items = {
                attr(n, "id"): posixpath.normpath(posixpath.join("Contents", attr(n, "href")))
                for n in manifest.iter()
                if local_name(n.tag) == "item"
            }
            ordered = [items.get(attr(n, "idref")) for n in manifest.iter() if local_name(n.tag) == "itemref"]
            ordered = [n for n in ordered if n in sections]
            if ordered:
                sections = ordered
            for name, key in (("title", "title"), ("creator", "author"), ("description", "description")):
                element = first(manifest, name)
                if element is not None and element.text:
                    result.metadata[key] = element.text
        if not sections:
            raise ParseError("INVALID_FILE", "HWPX has no body sections")
        for index, part in enumerate(sections, 1):
            if options.pages is not None and index not in options.pages:
                continue
            parser.part, parser.section = part, index
            root = archive.xml(part)
            sec_pr = first(root, "secPr")
            parser.outline_id = attr(sec_pr, "outlineShapeIDRef", "1") if sec_pr is not None else "1"
            parser.deleted = set()
            parser.mark_deletions(root)
            result.blocks.extend(parser.walk(root))
        result.page_count = len(sections)
        result.warnings.append(
            Diagnostic("SECTION_PAGES", "HWPX page ranges refer to sections, not rendered pages")
        )
    return result


def parse_hwpml(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "hwpml", page_mode="section")
    root = xml(data, options)
    parser = HangulXmlParser(options, result)
    parser.part = "document.xml"
    sections = [n for n in root.iter() if local_name(n.tag).lower() == "section"]
    if not sections:
        sections = [root]
    for index, section in enumerate(sections, 1):
        if options.pages is None or index in options.pages:
            parser.mark_deletions(section)
            result.blocks.extend(parser.walk(section))
    result.page_count = len(sections)
    return result
