"""Read worksheet shape text without treating floating drawings as cell values."""

from .models import Block, ParseError, SourceRef

DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
TEXT = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def drawing_text_blocks(archive, worksheet, relationships):
    blocks = []
    seen = set()

    def shapes(parent, part, depth=0):
        if depth > archive.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "Worksheet shape nesting exceeds budget")
        for node in parent:
            if node.tag not in (DRAWING + "sp", DRAWING + "grpSp"):
                continue
            properties = node.find(DRAWING + ("nvSpPr" if node.tag == DRAWING + "sp" else "nvGrpSpPr"))
            identity = properties.find(DRAWING + "cNvPr") if properties is not None else None
            if identity is not None and identity.get("hidden") in ("1", "true"):
                continue
            if node.tag == DRAWING + "grpSp":
                shapes(node, part, depth + 1)
                continue
            body = node.find(DRAWING + "txBody")
            if body is None:
                continue
            paragraphs = []
            for paragraph in body.findall(TEXT + "p"):
                paragraphs.append(
                    "".join(
                        item.text or "" if item.tag == TEXT + "t" else "\n"
                        for item in paragraph.iter()
                        if item.tag in (TEXT + "t", TEXT + "br")
                    )
                )
            text = "\n".join(paragraphs).strip()
            if text:
                anchor = "shape:" + identity.get("id", "") if identity is not None else None
                blocks.append(Block("paragraph", text, source=SourceRef(part, anchor)))

    for drawing in worksheet:
        if drawing.tag.rsplit("}", 1)[-1] != "drawing":
            continue
        part = relationships.get(drawing.get(RELATIONSHIP))
        if not part or part not in archive.names or part in seen:
            continue
        seen.add(part)
        for anchor in archive.xml(part):
            if anchor.tag in (
                DRAWING + "oneCellAnchor",
                DRAWING + "twoCellAnchor",
                DRAWING + "absoluteAnchor",
            ):
                shapes(anchor, part)
    return blocks
