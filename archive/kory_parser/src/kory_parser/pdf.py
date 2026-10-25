"""PDF text and table extraction with explicit point/top-left source coordinates."""

from __future__ import annotations

import base64
import re
from dataclasses import replace

from .hwp_numbering import format_number
from .models import (
    Block,
    Cell,
    Diagnostic,
    ParseError,
    ParseOptions,
    ParseResult,
    SourceRef,
    has_contents_title,
    table_from_cells,
)
from .pdf_continuation import join_pdf_parts, join_repeated_headers
from .pdf_geometry import (
    EdgeIndex,
    area,
    clip_grids,
    cluster,
    decorative_strip,
    distinct_grids,
    fill_grids,
    grid_cell_subset,
    inside,
    intersection,
)
from .pdf_layout import pdf_cell_text, visible_blocks
from .pdf_native import document_metadata, load_native_page, native_document
from .pdf_paragraphs import recover_paragraphs
from .pdf_reading import column_positions, reading_order, split_column_lines
from .pdf_rules import ruled_grids
from .pdf_text import CharacterIndex, dedupe_glyphs
from .pdf_typography import PdfTypography
from .pdf_words import extract_text, extract_words

CONTENTS_LEADER = re.compile(r"(?:[.·․…⋯]\s*){3,}\s*\d+\s*$")


def source(page: int, box, anchor: str = "") -> SourceRef:
    return SourceRef("pdf", anchor, page, tuple(round(v, 4) for v in box), "top_left", "pt")


def clean_pdf_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    return re.sub(r"(?<=[^\W_])(?:\s*[·․.]){5,}\s*(?=\d{1,4}\s*$)", " ", text)


def normalize_glyphs(chars: list[dict]) -> tuple[list[dict], int]:
    cleaned = []
    for char in chars:
        text = char["text"]
        if "\x00" in text:
            text = text.replace("\x00", "")
        if text:
            copied = char.copy()
            copied["text"] = text
            cleaned.append(copied)
    chars = dedupe_glyphs(cleaned, tolerance=0.3)
    circles = [(index, c) for index, c in enumerate(chars) if c["text"] in ("◯", "○", "〇")]
    if not circles:
        return chars, 0
    digit_items = {id(c): n for n, c in enumerate(chars) if len(c["text"]) == 1 and c["text"] in "0123456789"}
    if not digit_items:
        return chars, 0
    digit_index = CharacterIndex([c for c in chars if id(c) in digit_items])
    removed, replacements = set(), {}
    for index, circle in circles:
        digits = [
            (digit_items[id(c)], c)
            for c in digit_index.within(
                (circle["x0"], circle["top"], circle["x1"], circle["bottom"]), include_boundary=True
            )
            if digit_items[id(c)] not in removed and c["size"] <= circle["size"] * 1.1
        ]
        if not 1 <= len(digits) <= 2:
            continue
        digits.sort(key=lambda item: item[1]["x0"])
        number = int("".join(c["text"] for _, c in digits))
        replacements[index] = dict(
            circle, text="⓪" if number == 0 else format_number(number, "CIRCLED_DIGIT")
        )
        removed.update(n for n, _ in digits)
    return [replacements.get(n, c) for n, c in enumerate(chars) if n not in removed], len(replacements)


def extract_table(
    table,
    page,
    options: ParseOptions,
    chars: list[dict] | None = None,
    char_index: CharacterIndex | None = None,
    typography: PdfTypography | None = None,
    unframed_text: dict | None = None,
) -> Block:
    boxes = table.cells
    xs = cluster([x for box in boxes for x in (box[0], box[2])])
    ys = cluster([y for box in boxes for y in (box[1], box[3])])
    if (len(xs) - 1) * (len(ys) - 1) > options.max_cells:
        raise ParseError("RESOURCE_LIMIT", "PDF grid exceeds cell budget")
    nearest = lambda axis, value: min(range(len(axis)), key=lambda n: abs(axis[n] - value))
    char_index = (
        char_index if char_index is not None else CharacterIndex(page.chars if chars is None else chars)
    )
    addressed = []
    occupied = set()

    def cell_text(box):
        cell_chars = char_index.within(box)
        text = clean_pdf_text(extract_text(cell_chars, x_tolerance=2, y_tolerance=3)) if cell_chars else ""
        if unframed_text is not None and getattr(table, "strategy", "") == "clip" and cell_chars:
            ref = source(page.page_number, box)
            unframed_text[(ref.page, ref.bbox)] = paragraph_lines(
                cell_chars, ref.page, typography, columns=True, cuts=page.layout_cuts
            )
        # A borderless clip may later become an ordinary paragraph. Retain its
        # measured single-line style through that structural conversion.
        if typography is not None and getattr(table, "strategy", "") == "clip" and "\n" not in text.strip():
            typography.region(source(page.page_number, box), text.strip(), cell_chars)
        return text

    for box in boxes:
        left, top, right, bottom = (round(v, 2) for v in box)
        col, row = nearest(xs, left), nearest(ys, top)
        cs, rs = nearest(xs, right) - col, nearest(ys, bottom) - row
        positions = {(r, c) for r in range(row, row + rs) for c in range(col, col + cs)}
        if not positions or occupied & positions:
            continue
        occupied.update(positions)
        addressed.append((row, col, Cell(cell_text(box), rs, cs, source=source(page.page_number, box))))
    for r in range(len(ys) - 1):
        for c in range(len(xs) - 1):
            if (r, c) not in occupied:
                box = (xs[c], ys[r], xs[c + 1], ys[r + 1])
                addressed.append(
                    (r, c, Cell(cell_text(box), source=source(page.page_number, box, f"grid_fill:{r},{c}")))
                )
    grid = table_from_cells(
        len(ys) - 1, len(xs) - 1, addressed, replace(options, keep_trailing_empty_cols=True)
    )
    grid.regions = [source(page.page_number, table.bbox)]
    grid.geometry_source = getattr(table, "strategy", "line")
    return Block("table", table=grid, source=source(page.page_number, table.bbox))


def visible_geometry(obj: dict) -> bool:
    if obj.get("object_type") not in ("line", "rect", "curve"):
        return True
    color = obj.get("stroking_color") if obj.get("stroke", True) else obj.get("non_stroking_color")
    if color == 1 or isinstance(color, (tuple, list)) and color and all(c >= 0.99 for c in color):
        return False
    return obj.get("stroke", True) or min(obj.get("width", 100), obj.get("height", 100)) <= 1


def paragraph_lines(
    chars: list[dict], page_number: int, typography: PdfTypography | None = None, *, columns=False, cuts=None
) -> list[Block]:
    words = extract_words(chars, x_tolerance=2, y_tolerance=3, extra_attrs=["size"], return_chars=True)
    line_top = lambda w: w.get("layout_top", w["top"])
    lines: list[list[dict]] = []
    horizontal = [w for w in words if w["direction"] in ("ltr", "rtl")]
    for word in sorted(horizontal, key=lambda w: (line_top(w), w["x0"])):
        if lines and abs(line_top(lines[-1][0]) - line_top(word)) <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    if columns:
        lines = split_column_lines(lines, chars, cuts)
    vertical = {}
    for word in words:
        if word["direction"] not in ("ltr", "rtl"):
            key = (word["direction"], word["chars"][0].get("native_line", word["x0"]))
            vertical.setdefault(key, []).append(word)
    lines.extend(vertical.values())
    blocks = []
    for line in lines:
        direction = line[0]["direction"]
        if direction in ("ltr", "rtl"):
            line.sort(key=lambda w: w["x0"], reverse=direction == "rtl")
        else:
            line.sort(key=lambda w: w["top"], reverse=direction == "btt")
        box = (
            min(w["x0"] for w in line),
            min(w["top"] for w in line),
            max(w["x1"] for w in line),
            max(w["bottom"] for w in line),
        )
        raw_text = " ".join(w["text"] for w in line)
        blocks.append(
            Block(
                "paragraph",
                clean_pdf_text(raw_text),
                source=source(page_number, box),
            )
        )
        if typography is not None:
            typography.line(blocks[-1], [c for word in line for c in word["chars"]])
            if (
                typography.extract_contents
                and raw_text.rstrip()[-1:].isdigit()
                and (
                    CONTENTS_LEADER.search(raw_text)
                    or (
                        len(line) > 1
                        and line[-1]["text"].isdigit()
                        and line[-1]["x0"] - line[-2]["x1"] > line[-1]["chars"][0]["size"] * 1.6
                    )
                )
            ):
                ref = blocks[-1].source
                typography.contents_page_labels.add((ref.page, ref.bbox, blocks[-1].text))
    return blocks


def has_text(block: Block) -> bool:
    if block.table:
        return any(
            c.text.strip() or any(has_text(b) for b in c.blocks)
            for row in block.table.cells
            for c in row
            if not c.covered
        )
    return bool(block.text.strip())


def trim_pdf_columns(blocks: list[Block]) -> None:
    for block in blocks:
        table = block.table
        if table is None:
            continue
        for row in table.cells:
            for cell in row:
                trim_pdf_columns(cell.blocks)
        cols = table.cols
        while cols and all(
            not row[cols - 1].text.strip() and not row[cols - 1].blocks for row in table.cells
        ):
            cols -= 1
        if not cols or cols == table.cols:
            continue
        table.cells = [row[:cols] for row in table.cells]
        table.cols = cols
        for row in table.cells:
            for c, cell in enumerate(row):
                cell.col_span = min(cell.col_span, cols - c)


def parse_pdf(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "pdf", page_mode="layout")
    typography = PdfTypography(extract_contents=options.extract_contents)
    edge_indexes, page_sizes, boundary_parts, boundary_text = {}, {}, set(), {}
    unframed_text = {}
    with native_document(data) as document:
        result.page_count = document.page_count
        result.metadata = document_metadata(document)
        initial_doctop = 0
        for native in document:
            index = native.number + 1
            if options.pages is not None and index not in options.pages:
                initial_doctop += native.rect.height
                continue
            try:
                page = load_native_page(native, options, initial_doctop)
            except RuntimeError as error:
                raise ParseError("INVALID_FILE", "MuPDF page extraction failed") from error
            initial_doctop += page.height
            raw_clips = page.clips
            if page.unresolved_glyphs:
                result.warnings.append(
                    Diagnostic(
                        "UNRESOLVED_PDF_GLYPH",
                        f"{page.unresolved_glyphs} glyphs have no verified Unicode mapping",
                        SourceRef("pdf", page=index),
                    )
                )
            if len(page.chars) > options.max_xml_nodes or len(page.edges) > 100_000:
                raise ParseError("RESOURCE_LIMIT", "PDF page complexity exceeds budget")
            clean_chars, composed = normalize_glyphs(page.chars)
            page.layout_cuts = column_positions(clean_chars)
            char_index = CharacterIndex(clean_chars)
            typography.page(index, clean_chars, page.height)
            if composed:
                result.warnings.append(
                    Diagnostic(
                        "COMPOSED_GLYPH_RESTORED",
                        f"Restored {composed} enclosed number glyphs",
                        SourceRef("pdf", page=index),
                    )
                )
            geometry_page = page.filter(visible_geometry)
            edge_index = EdgeIndex(geometry_page.edges)
            edge_indexes[index] = edge_index
            page_sizes[index] = (page.width, page.height)
            clipped = (
                [
                    g
                    for g in clip_grids(geometry_page, options, raw_clips)
                    if not decorative_strip(g, clean_chars, edge_index)
                ]
                if clean_chars
                else []
            )
            filled = (
                [
                    g
                    for g in fill_grids(page, options, clean_chars)
                    if sum(intersection(g.bbox, c.bbox) for c in clipped) < area(g.bbox) * 0.5
                    and not decorative_strip(g, clean_chars, edge_index)
                ]
                if clean_chars
                else []
            )
            lined = ruled_grids(geometry_page.edges, options) if clean_chars else []
            # Consult complete ruled grids before overlapping text clips or
            # inferred shading can suppress those very grids as duplicates.
            retained = {id(grid) for grid in distinct_grids(clipped + filled, edge_index, lined)}
            clipped = [grid for grid in clipped if id(grid) in retained]
            filled = [grid for grid in filled if id(grid) in retained]
            candidates = (
                clipped
                + filled
                + [
                    grid
                    for grid in lined
                    if sum(intersection(grid.bbox, c.bbox) for c in clipped + filled) < area(grid.bbox) * 0.5
                    or any(
                        area(grid.bbox) > area(c.bbox) + 1
                        and len(grid.cells) > len(c.cells)
                        and grid_cell_subset(c, grid)
                        for c in clipped + filled
                    )
                ]
            )
            candidates = distinct_grids(candidates, edge_index)
            blocks = []
            tables = []
            for table in candidates:
                if len(table.cells) < 2 and getattr(table, "strategy", "") != "clip":
                    continue
                try:
                    block = extract_table(
                        table,
                        page,
                        options,
                        char_index=char_index,
                        typography=typography,
                        unframed_text=unframed_text,
                    )
                    if has_text(block):
                        tables.append((table, block))
                        if getattr(table, "boundary_part", False):
                            boundary_parts.add(id(block))
                except ParseError as error:
                    if error.code != "INVALID_TABLE":
                        raise
                    result.warnings.append(
                        Diagnostic(
                            "INVALID_TABLE", "Ambiguous PDF grid retained as text", source(index, table.bbox)
                        )
                    )
            # Small contained tables are placed under the enclosing cell rather than emitted twice.
            consumed = set()
            for small_index, (small, small_block) in enumerate(tables):
                parents = [
                    (area(big.bbox), parent_index, big, parent_block)
                    for parent_index, (big, parent_block) in enumerate(tables)
                    if parent_index != small_index
                    and area(big.bbox) > area(small.bbox)
                    and inside(small.bbox, big.bbox)
                ]
                for _, parent_index, parent, parent_block in sorted(parents):
                    found = False
                    for row in parent_block.table.cells:
                        for cell in row:
                            if cell.source and cell.source.bbox and inside(small.bbox, cell.source.bbox):
                                cell.blocks.append(small_block)
                                consumed.add(small_index)
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
            # Assemble each nested cell once, preserving text outside inner tables.
            for _, block in sorted(tables, key=lambda pair: area(pair[0].bbox)):
                for row in block.table.cells:
                    for cell in row:
                        if not cell.blocks or not cell.source or not cell.source.bbox:
                            continue
                        inner_boxes = [b.source.bbox for b in cell.blocks if b.source and b.source.bbox]
                        own = [
                            c
                            for c in char_index.within(cell.source.bbox)
                            if not any(
                                box[0] <= (c["x0"] + c["x1"]) / 2 < box[2]
                                and box[1] <= (c["top"] + c["bottom"]) / 2 < box[3]
                                for box in inner_boxes
                            )
                        ]
                        cell.blocks.extend(
                            paragraph_lines(own, index, typography, columns=True, cuts=page.layout_cuts)
                        )
                        cell.blocks.sort(key=lambda b: (b.source.bbox[1], b.source.bbox[0]))
                        cell.text = pdf_cell_text(cell.blocks)
            for n, (table, block) in enumerate(tables):
                if n not in consumed:
                    if id(block) in boundary_parts and not block.table.cells[0][0].blocks:
                        box = table.bbox
                        chars = char_index.within(box)
                        boundary_text[id(block)] = paragraph_lines(
                            chars, index, typography, columns=True, cuts=page.layout_cuts
                        )
                    blocks.append((block.source.bbox[1], block.source.bbox[0], block))
            body_chars = [
                w
                for w in clean_chars
                if not any(
                    table.bbox[0] <= (w["x0"] + w["x1"]) / 2 < table.bbox[2]
                    and table.bbox[1] <= (w["top"] + w["bottom"]) / 2 < table.bbox[3]
                    for table, _ in tables
                )
            ]
            for block in paragraph_lines(body_chars, index, typography, columns=True, cuts=page.layout_cuts):
                blocks.append((block.source.bbox[1], block.source.bbox[0], block))
            for n, image in enumerate(page.images):
                box = (image["x0"], image["top"], image["x1"], image["bottom"])
                ref = source(index, box, f"image:{n}")
                block = Block("image", source=ref)
                if options.images:
                    if image.get("image_bytes"):
                        block.image_data = base64.b64encode(image["image_bytes"]).decode()
                        extension = image.get("image_ext", "")
                        block.mime_type = (
                            "image/jpeg" if extension in ("jpg", "jpeg") else f"image/{extension}"
                        )
                    stream = image.get("stream")
                    if stream:
                        block.image_data = base64.b64encode(stream.get_data()).decode()
                        block.mime_type = "application/octet-stream"
                blocks.append((box[1], box[0], block))
                result.warnings.append(
                    Diagnostic("UNEXTRACTED_IMAGE_TEXT", "PDF image content requires review", ref)
                )
            if not page.chars:
                ref = source(index, (0, 0, page.width, page.height))
                result.warnings.append(Diagnostic("NEEDS_OCR", "PDF page has no extractable text", ref))
                if options.ocr:
                    from .ocr import ocr_pdf_page

                    for block in ocr_pdf_page(data, index, options):
                        blocks.append((block.source.bbox[1], block.source.bbox[0], block))
            result.blocks.extend(b for _, _, b in sorted(blocks, key=lambda v: (v[0], v[1])))
    result.blocks = join_pdf_parts(
        result.blocks, boundary_parts, edge_indexes, page_sizes, options, boundary_text
    )
    result.blocks = visible_blocks(result.blocks, edge_indexes, options, unframed_text)
    result.blocks = join_repeated_headers(result.blocks, page_sizes, options, result.warnings)
    typography.headings(result.blocks)
    result.blocks = reading_order(result.blocks, page_sizes)
    if options.extract_contents and has_contents_title(result.blocks):
        from .document_contents import recover_contents

        result.contents = recover_contents(result.blocks, page_sizes, typography.contents_page_labels)
    result.blocks = recover_paragraphs(result.blocks, typography)
    if not options.keep_trailing_empty_cols:
        trim_pdf_columns(result.blocks)
    if not any(has_text(b) for b in result.blocks):
        result.success = False
        result.error_code = "NEEDS_OCR"
    return result
