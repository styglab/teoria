"""Addressable evidence views over saved kordoc output; no parsing or I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    node_id: str
    quote: str = Field(min_length=1)


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    native_ref: str
    kind: str
    text: str
    parent_id: str | None
    page: int | None
    row: int | None = None
    column: int | None = None
    row_span: int | None = None
    column_span: int | None = None
    source_table_id: str | None = None


@dataclass(frozen=True)
class ParsedEvidenceDocument:
    document_id: str
    parse_run_id: str
    native_sha256: str
    nodes: tuple[EvidenceNode, ...]
    unreadable_refs: tuple[str, ...]
    warnings: tuple[str, ...]

    def context(self) -> dict:
        return {
            "document_id": self.document_id,
            "parse_run_id": self.parse_run_id,
            "native_sha256": self.native_sha256,
            "nodes": [asdict(n) for n in self.nodes],
            "unreadable_refs": list(self.unreadable_refs),
            "warnings": list(self.warnings),
        }


def comparable_text(value: str) -> str:
    # Preserve digits, decimal points, units and negations. No fuzzy matching.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def build_document_evidence(
    native: dict, *, document_id: str, parse_run_id: str, native_sha256: str,
) -> ParsedEvidenceDocument:
    if not document_id or not parse_run_id or not re.fullmatch(r"[0-9a-f]{64}", native_sha256):
        raise ValueError("document identity and native SHA-256 required")
    if not native.get("success"):
        raise ValueError("unsuccessful native parse")
    nodes: list[EvidenceNode] = []
    unreadable: list[str] = []

    def add(kind, text, ref, parent, page, **extra):
        n = EvidenceNode(f"n{len(nodes):05}", ref, kind, text, parent, page, **extra)
        nodes.append(n)
        return n.node_id

    def walk(blocks, ref="/blocks", parent=None, inherited_page=None):
        for i, block in enumerate(blocks):
            path = f"{ref}/{i}"
            page = block.get("pageNumber", inherited_page)
            kind = block.get("type", "unknown")
            # Parent cell text is a flattened duplicate when nested blocks exist.
            node = add(kind, block.get("text") or "", path, parent, page)
            if kind == "image":
                unreadable.append(path)
            table = block.get("table")
            if table:
                for ri, row in enumerate(table.get("cells", [])):
                    for ci, cell in enumerate(row):
                        cp = f"{path}/table/cells/{ri}/{ci}"
                        nested = cell.get("blocks") or []
                        cell_id = add(
                            "cell", "" if nested else cell.get("text", ""), cp, node, page,
                            row=ri, column=ci, row_span=cell.get("rowSpan", 1),
                            column_span=cell.get("colSpan", 1), source_table_id=table.get("sourceId"),
                        )
                        walk(nested, cp + "/blocks", cell_id, page)
            walk(block.get("children") or [], path + "/children", node, page)
            walk(block.get("footnoteBlocks") or [], path + "/footnoteBlocks", node, page)
            if table:
                walk(table.get("captionBlocks") or [], path + "/table/captionBlocks", node, page)

    walk(native.get("blocks") or [])
    warnings = tuple(w.get("code", "UNKNOWN") for w in native.get("warnings", []) if isinstance(w, dict))
    if not any(n.kind != "image" and n.text.strip() for n in nodes):
        unreadable.append("/document:no_extractable_text")
    if any(w in {"PARTIAL_PARSE", "NEEDS_OCR", "SKIPPED_IMAGE"} for w in warnings):
        unreadable.append("/document:parser_warning")
    return ParsedEvidenceDocument(document_id, parse_run_id, native_sha256, tuple(nodes), tuple(unreadable), warnings)


def validate_evidence(quotes: list[EvidenceQuote], documents: list[ParsedEvidenceDocument]) -> list[str]:
    lookup = {(d.document_id, n.node_id): n for d in documents for n in d.nodes}
    if len({d.document_id for d in documents}) != len(documents):
        raise ValueError("duplicate document identity")
    errors = []
    if not quotes:
        errors.append("missing_evidence")
    for q in quotes:
        node = lookup.get((q.document_id, q.node_id))
        if node is None:
            errors.append("unknown_evidence_node")
        elif not comparable_text(q.quote) or comparable_text(q.quote) not in comparable_text(node.text):
            errors.append("quote_not_in_source")
        elif node.kind == "image":
            errors.append("unreadable_image_evidence")
    return sorted(set(errors))


def literal(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))

def source_quote(doc,a):
 ev=a.get('evidence',{});nodes={n['node_id']:n['text'] for n in doc['parsed_document']['nodes']}
 if 'node_id' in ev:
  text=nodes[ev['node_id']];return text[ev.get('char_start',0):ev.get('char_end',len(text))]
 return '\n'.join(nodes.get(id,'') for id in ev.get('source_node_ids',[]))


def attribute_is_grounded(document,attribute):
    """Check literal conditions without deciding their domain meaning."""
    try:
        quote=literal(source_quote(document,attribute))
    except (KeyError,TypeError,ValueError):
        return False
    value=attribute.get('value_raw')
    if not value or not literal(value) or literal(value) not in quote:return False
    fields=[attribute.get('unit_raw'),attribute.get('operator_raw'),*attribute.get('qualifiers_raw',[])]
    return all(not value or bool(literal(value)) and literal(value) in quote for value in fields)
