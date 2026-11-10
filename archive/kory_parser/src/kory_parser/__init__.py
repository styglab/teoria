"""Python document parser with structured output and source references."""

from .api import parse
from .models import (
    Block,
    Cell,
    ContentsEntry,
    Diagnostic,
    DocumentContents,
    ParseOptions,
    ParseResult,
    SourceRef,
    Span,
    Table,
)
from .version import __version__ as __version__

__all__ = [
    "Block",
    "Cell",
    "ContentsEntry",
    "Diagnostic",
    "DocumentContents",
    "ParseOptions",
    "ParseResult",
    "SourceRef",
    "Span",
    "Table",
    "parse",
]
