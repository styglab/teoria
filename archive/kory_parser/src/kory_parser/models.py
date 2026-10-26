"""Python document contract. Coordinates always identify their origin and unit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .version import __version__


@dataclass(frozen=True)
class ParseOptions:
    pdf_backend: Literal["pymupdf"] = "pymupdf"
    ocr: bool = False
    images: bool = False
    keep_empty_paragraphs: bool = True
    keep_trailing_empty_cols: bool | None = None
    sheet_layout: Literal["compact", "source"] = "compact"
    pages: tuple[int, ...] | None = None
    max_input_bytes: int = 100 * 1024 * 1024
    max_expanded_bytes: int = 200 * 1024 * 1024
    max_xml_nodes: int = 1_000_000
    max_cells: int = 100_000
    max_depth: int = 32
    extract_contents: bool = False
    recover_numbered_structure: bool = True

    def __post_init__(self) -> None:
        for name in ("max_input_bytes", "max_expanded_bytes", "max_xml_nodes", "max_cells", "max_depth"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.pdf_backend != "pymupdf":
            raise ValueError("Only the pymupdf PDF engine is supported")
        if self.pages is not None and any(p < 1 for p in self.pages):
            raise ValueError("pages are 1-based")
        if self.sheet_layout not in ("compact", "source"):
            raise ValueError("sheet_layout must be compact or source")


@dataclass(frozen=True)
class SourceRef:
    part: str
    anchor: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    coordinate_system: str | None = None
    unit: str | None = None


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    script: Literal["sup", "sub"] | None = None


@dataclass
class Cell:
    text: str = ""
    row_span: int = 1
    col_span: int = 1
    blocks: list[Block] = field(default_factory=list)
    source: SourceRef | None = None
    is_header: bool = False
    covered: bool = False


@dataclass
class Table:
    rows: int
    cols: int
    cells: list[list[Cell]]
    source_id: str | None = None
    caption: str | None = None
    has_header: bool = False
    regions: list[SourceRef] = field(default_factory=list)
    geometry_source: Literal["clip", "line", "fill", "text"] | None = None


@dataclass
class Block:
    type: Literal["paragraph", "heading", "list", "table", "image", "separator"]
    text: str = ""
    table: Table | None = None
    level: int | None = None
    source: SourceRef | None = None
    spans: list[Span] = field(default_factory=list)
    children: list[Block] = field(default_factory=list)
    image_data: str | None = None  # base64, only on explicit images=True
    mime_type: str | None = None
    inline_continuation: bool = False
    regions: list[SourceRef] = field(default_factory=list)


@dataclass
class Diagnostic:
    code: str
    message: str
    source: SourceRef | None = None


@dataclass
class ContentsEntry:
    entry_id: str
    title: str
    number: str | None
    level: int | None
    parent_id: str | None
    printed_page_label: str | None
    source: SourceRef | None
    regions: list[SourceRef] = field(default_factory=list)
    target: SourceRef | None = None
    target_status: Literal["resolved", "unresolved", "ambiguous"] = "unresolved"


@dataclass
class DocumentContents:
    title: str
    source: SourceRef | None
    entries: list[ContentsEntry] = field(default_factory=list)


@dataclass
class ParseResult:
    success: bool
    file_type: str
    blocks: list[Block] = field(default_factory=list)
    markdown: str = ""
    metadata: dict = field(default_factory=dict)
    warnings: list[Diagnostic] = field(default_factory=list)
    error_code: str | None = None
    page_count: int | None = None
    page_mode: str | None = None
    sha256: str = ""
    parser_version: str = __version__
    schema_version: str = "1"
    contents: list[DocumentContents] = field(default_factory=list)

    def to_dict(self) -> dict:
        def optional_regions(value):
            if isinstance(value, dict):
                if "type" in value and not value.get("regions"):
                    value.pop("regions", None)
                return {key: optional_regions(item) for key, item in value.items()}
            if isinstance(value, list):
                return [optional_regions(item) for item in value]
            return value

        result = optional_regions(asdict(self))
        if not result["contents"]:
            result.pop("contents")
        return result


class ParseError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def has_contents_title(blocks: list[Block]) -> bool:
    """Cheap model-tree guard so ordinary documents need no TOC reader import."""
    titles = {"목차", "차례", "contents", "tableofcontents", "shortcontents"}

    def matches(text):
        return any(
            "".join(line.split()).strip("<〈《【[>〉》】]").casefold() in titles for line in text.splitlines()
        )

    for block in blocks:
        if matches(block.text) or has_contents_title(block.children):
            return True
        if block.table:
            for row in block.table.cells:
                for cell in row:
                    if not cell.covered and (matches(cell.text) or has_contents_title(cell.blocks)):
                        return True
    return False


def table_from_cells(
    rows: int,
    cols: int,
    addressed: list[tuple[int, int, Cell]],
    options: ParseOptions,
    source_id: str | None = None,
) -> Table:
    """Place real anchor cells, retaining explicit placeholders for covered positions."""
    if rows < 1 or cols < 1 or rows * cols > options.max_cells:
        raise ParseError("RESOURCE_LIMIT", "Invalid or oversized table grid")
    pending: list[list[Cell | None]] = [[None] * cols for _ in range(rows)]
    for row, col, cell in addressed:
        if row < 0 or col < 0 or cell.row_span < 1 or cell.col_span < 1:
            raise ParseError("INVALID_TABLE", "Invalid cell address or span")
        if row + cell.row_span > rows or col + cell.col_span > cols:
            raise ParseError("INVALID_TABLE", "Cell extends beyond declared table")
        if cell.row_span == cell.col_span == 1:
            if pending[row][col] is not None:
                raise ParseError("INVALID_TABLE", "Overlapping table cells")
            pending[row][col] = cell
            continue
        if any(
            pending[r][c] is not None
            for r in range(row, row + cell.row_span)
            for c in range(col, col + cell.col_span)
        ):
            raise ParseError("INVALID_TABLE", "Overlapping table cells")
        pending[row][col] = cell
        for r in range(row, row + cell.row_span):
            for c in range(col, col + cell.col_span):
                if r != row or c != col:
                    pending[r][c] = Cell(covered=True)
    grid = [[cell if cell is not None else Cell() for cell in row] for row in pending]
    if not options.keep_trailing_empty_cols:
        used = max(
            (
                c + 1
                for r in grid
                for c, cell in enumerate(r)
                if not cell.covered and (cell.text or cell.blocks)
            ),
            default=cols,
        )
        if used < cols:
            for row in grid:
                for col, cell in enumerate(row[:used]):
                    cell.col_span = min(cell.col_span, used - col)
            cols = used
            grid = [row[:cols] for row in grid]
    return Table(rows, cols, grid, source_id=source_id, has_header=rows > 1)


def plain_text(blocks: list[Block]) -> str:
    text = ""
    for block in blocks:
        if block.table:
            rows = [
                " / ".join(c.text.strip().replace("\n", " ") for c in row if not c.covered and c.text.strip())
                for row in block.table.cells
            ]
            value = "\n".join(r for r in rows if r)
        elif block.type == "image":
            value = f"![image]({block.text})" if block.text else "[image]"
        else:
            value = block.text
        if value:
            text += (" " if block.inline_continuation else "\n") if text else ""
            text += value
        if block.children:
            child_text = plain_text(block.children)
            text += ("\n" if text and child_text else "") + child_text
    return text
