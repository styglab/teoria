"""Native OOXML readers and BIFF workbook parsing. No office application or Node dependency."""

from __future__ import annotations

import base64
import posixpath
import re
from dataclasses import replace

from .document_io import DocumentZip, local_name
from .hangul_xml import attr, first
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
from .office_numbering import DocxNumbering
from .xlsx_worksheet import worksheet_xml


def relationships(archive: DocumentZip, part: str) -> dict[str, str]:
    directory, name = posixpath.split(part)
    rels = posixpath.join(directory, "_rels", name + ".rels")
    if rels not in archive.names:
        return {}
    return {
        attr(n, "Id"): attr(n, "Target")
        if attr(n, "TargetMode") == "External"
        else posixpath.normpath(posixpath.join(directory, attr(n, "Target")))
        for n in archive.xml(rels)
    }


def metadata(archive: DocumentZip) -> dict:
    if "docProps/core.xml" not in archive.names:
        return {}
    aliases = {
        "title": "title",
        "creator": "author",
        "description": "description",
        "created": "created_at",
        "modified": "modified_at",
    }
    return {
        aliases[local_name(n.tag)]: n.text
        for n in archive.xml("docProps/core.xml")
        if local_name(n.tag) in aliases and n.text
    }


class DocxParser:
    def __init__(self, archive: DocumentZip, options: ParseOptions, result: ParseResult):
        self.archive, self.options, self.result = archive, options, result
        self.part = "word/document.xml"
        self.rels = relationships(archive, self.part)
        self.styles = {}
        self.sequence = 0
        self.numbering = DocxNumbering(archive, options.max_depth)
        if "word/styles.xml" in archive.names:
            for style in archive.xml("word/styles.xml"):
                name = first(style, "name")
                outline = first(style, "outlineLvl")
                label = attr(name, "val") if name is not None else ""
                self.styles[attr(style, "styleId")] = (
                    int(attr(outline, "val")) + 1
                    if outline is not None
                    else (
                        int(re.search(r"heading\s*(\d+)", label, re.IGNORECASE).group(1))
                        if re.search(r"heading\s*(\d+)", label, re.IGNORECASE)
                        else None
                    )
                )

    def ref(self, anchor: str) -> SourceRef:
        return SourceRef(self.part, anchor)

    def walk(self, parent, depth: int = 0) -> list[Block]:
        if depth > self.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "OOXML nesting exceeds budget")
        out = []
        for node in parent:
            name = local_name(node.tag)
            if name == "p":
                out.extend(self.paragraph(node))
            elif name == "tbl":
                out.append(self.table(node, depth + 1))
            elif name not in ("del", "moveFrom", "sectPr", "tblPr", "tcPr", "trPr", "sdtPr", "tblGrid"):
                out.extend(self.walk(node, depth + 1))
        return out

    def paragraph(self, node) -> list[Block]:
        self.sequence += 1
        anchor = attr(node, "paraId") or f"p[{self.sequence}]"
        spans = []
        images = []

        def visit(current) -> None:
            name = local_name(current.tag)
            if name in ("del", "moveFrom", "pPr", "rPr", "instrText", "delText"):
                return
            if name == "r":
                properties = next((c for c in current if local_name(c.tag) == "rPr"), None)
                flags = {}
                if properties is not None:
                    for prop, key in (
                        ("b", "bold"),
                        ("i", "italic"),
                        ("u", "underline"),
                        ("strike", "strike"),
                    ):
                        item = first(properties, prop)
                        flags[key] = item is not None and attr(item, "val", "true") not in (
                            "0",
                            "false",
                            "none",
                        )
                    script = first(properties, "vertAlign")
                    if script is not None:
                        flags["script"] = {"superscript": "sup", "subscript": "sub"}.get(attr(script, "val"))
                for item in current.iter():
                    kind = local_name(item.tag)
                    if kind in ("t", "tab", "br", "cr", "noBreakHyphen"):
                        value = (
                            item.text or ""
                            if kind == "t"
                            else "\t"
                            if kind == "tab"
                            else "-"
                            if kind == "noBreakHyphen"
                            else "\n"
                        )
                        spans.append(Span(value, **flags))
                    elif kind == "blip":
                        path = self.rels.get(attr(item, "embed"), "")
                        block = Block("image", source=self.ref(path or anchor))
                        if self.options.images and path in self.archive.names:
                            block.image_data = base64.b64encode(self.archive.read(path)).decode()
                        images.append(block)
                        self.result.warnings.append(
                            Diagnostic(
                                "UNEXTRACTED_IMAGE_TEXT", "Embedded image text not extracted", block.source
                            )
                        )
                return
            for child in current:
                visit(child)

        visit(node)
        text = "".join(s.text for s in spans).strip()
        style = first(node, "pStyle")
        outline = first(node, "outlineLvl")
        level = (
            int(attr(outline, "val")) + 1
            if outline is not None
            else self.styles.get(attr(style, "val") if style is not None else "")
        )
        properties = self.numbering.properties(node)
        if "outlineLvl" in properties:
            level = properties["outlineLvl"] + 1 if properties["outlineLvl"] < 9 else None
        prefix, list_level, warning = self.numbering.prefix(properties) if text else ("", None, None)
        if warning:
            self.result.warnings.append(
                Diagnostic(warning, "Automatic numbering could not be fully rendered", self.ref(anchor))
            )
        if prefix:
            text = prefix + text
            spans.insert(0, Span(prefix))
        kind = "heading" if level else "list" if list_level else "paragraph"
        if kind == "list":
            level = list_level
        blocks = (
            [Block(kind, text, level=level, spans=spans, source=self.ref(anchor))]
            if text or self.options.keep_empty_paragraphs
            else []
        )
        return blocks + images

    def table(self, node, depth: int) -> Block:
        addressed = []
        continuations: dict[tuple[int, int], tuple[int, Cell]] = {}
        rows, cols = 0, 0
        for row in node:
            if local_name(row.tag) != "tr":
                continue
            before = first(row, "gridBefore")
            col = int(attr(before, "val", "0")) if before is not None else 0
            current = {}
            for cell_node in row:
                if local_name(cell_node.tag) != "tc":
                    continue
                props = next((c for c in cell_node if local_name(c.tag) == "tcPr"), None)
                span = first(props, "gridSpan") if props is not None else None
                cs = int(attr(span, "val", "1")) if span is not None else 1
                merge = first(props, "vMerge") if props is not None else None
                key = (col, cs)
                if merge is not None and attr(merge, "val") != "restart":
                    if key not in continuations:
                        raise ParseError("INVALID_TABLE", "DOCX vertical merge has no anchor")
                    initial_row, cell = continuations[key]
                    cell.row_span += 1
                    current[key] = (initial_row, cell)
                else:
                    body = self.walk(cell_node, depth + 1)
                    cell = Cell(
                        plain_text(body),
                        col_span=cs,
                        blocks=body if any(b.type in ("table", "image") for b in body) else [],
                        source=self.ref(f"table[{self.sequence}]/cell[{rows},{col}]"),
                    )
                    addressed.append((rows, col, cell))
                    if merge is not None:
                        current[key] = (rows, cell)
                col += cs
            continuations = current
            cols = max(cols, col)
            rows += 1
        table = table_from_cells(rows, cols, addressed, self.options)
        return Block("table", table=table, source=self.ref(f"table[{self.sequence}]"))


def parse_docx(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "docx")
    with DocumentZip(data, options) as archive:
        parser = DocxParser(archive, options, result)
        root = archive.xml("word/document.xml")
        body = first(root, "body")
        if body is None:
            raise ParseError("INVALID_FILE", "DOCX body missing")
        result.blocks = parser.walk(body)
        result.metadata = metadata(archive)
        if options.pages is not None:
            raise ParseError("UNSUPPORTED_OPTION", "DOCX has no reliable page boundaries")
    return result


def column_index(address: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Za-z]+)\$?(\d+)", address)
    if not match:
        raise ParseError("INVALID_FILE", "Invalid spreadsheet cell address")
    col = 0
    for char in match.group(1).upper():
        col = col * 26 + ord(char) - 64
    return int(match.group(2)) - 1, col - 1


def sheet_table(rows: int, cols: int, values: dict[tuple[int, int], Cell], options: ParseOptions):
    """Compact presentation coordinates while retaining each cell's original source address."""
    if options.sheet_layout == "source":
        return table_from_cells(
            rows,
            cols,
            [(r, c, cell) for (r, c), cell in values.items()],
            replace(options, keep_trailing_empty_cols=True),
        )
    row_axis = sorted({r for (r, _), cell in values.items() if cell.text})
    col_axis = sorted({c for (_, c), cell in values.items() if cell.text})
    if not row_axis or not col_axis:
        return None
    row_ids, col_ids = {r: i for i, r in enumerate(row_axis)}, {c: i for i, c in enumerate(col_axis)}
    addressed = []
    for (r, c), cell in values.items():
        kept_rows = [rr for rr in row_axis if r <= rr < r + cell.row_span]
        kept_cols = [cc for cc in col_axis if c <= cc < c + cell.col_span]
        if not kept_rows or not kept_cols:
            continue
        cell.row_span, cell.col_span = len(kept_rows), len(kept_cols)
        addressed.append((row_ids[kept_rows[0]], col_ids[kept_cols[0]], cell))
    return table_from_cells(len(row_axis), len(col_axis), addressed, options)


def parse_xlsx(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "xlsx", page_mode="sheet")
    with DocumentZip(data, options) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.names:
            strings = [
                "".join(n.text or "" for n in item.iter() if local_name(n.tag) == "t")
                for item in archive.xml("xl/sharedStrings.xml")
            ]
        rels = relationships(archive, "xl/workbook.xml")
        sheets = [n for n in archive.xml("xl/workbook.xml").iter() if local_name(n.tag) == "sheet"]
        for index, sheet in enumerate(sheets, 1):
            if options.pages is not None and index not in options.pages:
                continue
            path = rels.get(attr(sheet, "id"))
            if not path or path not in archive.names:
                raise ParseError("INVALID_FILE", "Workbook sheet relationship missing")
            root = worksheet_xml(archive.read(path), options)
            values = {}
            for node in root.iter():
                if local_name(node.tag) != "c":
                    continue
                address = attr(node, "r")
                row, col = column_index(address)
                value = first(node, "v")
                text = value.text or "" if value is not None else ""
                if attr(node, "t") == "s":
                    string_index = int(text)
                    if not 0 <= string_index < len(strings):
                        raise ParseError("INVALID_FILE", "Workbook shared string index out of range")
                    text = strings[string_index]
                elif attr(node, "t") == "inlineStr":
                    text = "".join(n.text or "" for n in node.iter() if local_name(n.tag) == "t")
                elif attr(node, "t") == "b":
                    text = "TRUE" if text == "1" else "FALSE"
                formula = first(node, "f")
                if formula is not None and not text:
                    text = "=" + (formula.text or "")
                    result.warnings.append(
                        Diagnostic(
                            "FORMULA_NO_CACHE", "Formula has no cached value", SourceRef(path, address)
                        )
                    )
                if text:
                    values[(row, col)] = Cell(text, source=SourceRef(path, address))
            merges = []
            for node in root.iter():
                if local_name(node.tag) == "mergeCell":
                    begin, end = attr(node, "ref").split(":")
                    r, c = column_index(begin)
                    er, ec = column_index(end)
                    merges.append((r, c, er, ec))
            if not values:
                continue
            rows = max(r for r, _ in values) + 1
            cols = max(c for _, c in values) + 1
            for r, c, er, ec in merges:
                rows, cols = max(rows, er + 1), max(cols, ec + 1)
                cell = values.setdefault((r, c), Cell(source=SourceRef(path, f"R{r + 1}C{c + 1}")))
                cell.row_span, cell.col_span = er - r + 1, ec - c + 1
                for key in list(values):
                    if key != (r, c) and r <= key[0] <= er and c <= key[1] <= ec:
                        del values[key]
            result.blocks.append(Block("heading", attr(sheet, "name"), level=1, source=SourceRef(path)))
            table = sheet_table(rows, cols, values, options)
            if table is not None:
                result.blocks.append(Block("table", table=table, source=SourceRef(path)))
        result.page_count = len(sheets)
        result.metadata = metadata(archive)
    return result


def parse_xls(data: bytes, options: ParseOptions) -> ParseResult:
    import xlrd

    result = ParseResult(True, "xls", page_mode="sheet")
    book = xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True)
    try:
        result.page_count = book.nsheets
        for index in range(book.nsheets):
            if options.pages is not None and index + 1 not in options.pages:
                continue
            sheet = book.sheet_by_index(index)
            if not sheet.nrows or not sheet.ncols:
                continue
            if sheet.nrows * sheet.ncols > options.max_cells:
                raise ParseError("RESOURCE_LIMIT", "Workbook grid exceeds budget")
            merged = {(r, c): (re - r, ce - c) for r, re, c, ce in sheet.merged_cells}
            covered = {
                (rr, cc)
                for r, re, c, ce in sheet.merged_cells
                for rr in range(r, re)
                for cc in range(c, ce)
                if (rr, cc) != (r, c)
            }
            addressed = []
            for r in range(sheet.nrows):
                for c in range(sheet.ncols):
                    if (r, c) in covered:
                        continue
                    value = sheet.cell_value(r, c)
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                    rs, cs = merged.get((r, c), (1, 1))
                    addressed.append(
                        (r, c, Cell(str(value), rs, cs, source=SourceRef(sheet.name, f"R{r + 1}C{c + 1}")))
                    )
            result.blocks.extend(
                [
                    Block("heading", sheet.name, level=1),
                    Block("table", table=table_from_cells(sheet.nrows, sheet.ncols, addressed, options)),
                ]
            )
    finally:
        book.release_resources()
    return result


def parse_pptx(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "pptx", page_mode="slide")
    with DocumentZip(data, options) as archive:
        rels = relationships(archive, "ppt/presentation.xml")
        slides = [n for n in archive.xml("ppt/presentation.xml").iter() if local_name(n.tag) == "sldId"]
        result.page_count = len(slides)
        for index, slide in enumerate(slides, 1):
            if options.pages is not None and index not in options.pages:
                continue
            # sldId has both a numeric id and r:id; resolve the relationship namespace explicitly.
            key = next((v for k, v in slide.attrib.items() if k.endswith("}id")), "")
            part = rels.get(key, "")
            root = archive.xml(part)
            if attr(root, "show", "1") == "0":
                continue
            tree = first(root, "spTree")
            if tree is None:
                continue

            def shape(node, depth=0, part=part, index=index):
                if depth > options.max_depth:
                    raise ParseError("RESOURCE_LIMIT", "Slide group nesting exceeds budget")
                name = local_name(node.tag)
                source = SourceRef(part, attr(node, "id") or name, page=index)
                if name == "tbl":
                    rows = [c for c in node if local_name(c.tag) == "tr"]
                    grid = next((c for c in node if local_name(c.tag) == "tblGrid"), None)
                    cols = len(grid) if grid is not None else 0
                    addressed = []
                    for r, row in enumerate(rows):
                        for c, cell_node in enumerate(n for n in row if local_name(n.tag) == "tc"):
                            if attr(cell_node, "hMerge") == "1" or attr(cell_node, "vMerge") == "1":
                                continue
                            text = "\n".join(
                                "".join(n.text or "" for n in p.iter() if local_name(n.tag) == "t")
                                for p in cell_node.iter()
                                if local_name(p.tag) == "p"
                            )
                            addressed.append(
                                (
                                    r,
                                    c,
                                    Cell(
                                        text,
                                        int(attr(cell_node, "rowSpan", "1")),
                                        int(attr(cell_node, "gridSpan", "1")),
                                        source=source,
                                    ),
                                )
                            )
                    result.blocks.append(
                        Block(
                            "table",
                            table=table_from_cells(len(rows), cols, addressed, options),
                            source=source,
                        )
                    )
                    return
                if name == "p":
                    text = "".join(n.text or "" for n in node.iter() if local_name(n.tag) == "t")
                    if text or options.keep_empty_paragraphs:
                        result.blocks.append(Block("paragraph", text, source=source))
                    return
                if name == "pic":
                    result.blocks.append(Block("image", source=source))
                    result.warnings.append(
                        Diagnostic("UNEXTRACTED_IMAGE_TEXT", "Slide image text not extracted", source)
                    )
                    return
                for child in node:
                    shape(child, depth + 1)

            shape(tree)
        result.metadata = metadata(archive)
    return result
