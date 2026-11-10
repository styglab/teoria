"""Independent source review support for manual numbering evaluations.

Paragraph identities use normalized text and occurrence, not a parser's block
index: empty paragraphs and pictures legitimately change that index by engine.
"""

from collections import defaultdict
from zipfile import ZipFile

from defusedxml import ElementTree


def name(node):
    return node.tag.rsplit("}", 1)[-1].lower()


def paragraph_text(node):
    """Read literal XML text, including lineBreak tails; ignore embedded objects."""
    def read(element, in_text=False):
        tag = name(element)
        if tag in {"tbl", "table", "pic", "picture", "ctrl", "linesegarray", "secpr"}:
            return ""
        if tag in {"linebreak", "br"}:
            return "\n"
        if tag == "tab":
            return "\t"
        if tag in {"nbspace", "fwspace"}:
            return " "
        textual = in_text or tag in {"t", "char"}
        pieces = [element.text or ""] if textual else []
        for child in element:
            pieces.append(read(child, textual))
            if textual:
                pieces.append(child.tail or "")
        return "".join(pieces)
    return read(node)


def source_paragraphs(path):
    with ZipFile(path) as archive:
        for part in sorted(archive.namelist()):
            if not (part.startswith("Contents/section") and part.endswith(".xml")):
                continue
            root = ElementTree.fromstring(archive.read(part))
            for index, node in enumerate(root):
                if name(node) != "p" or any(name(c) in {"tbl", "table"} for c in node.iter()):
                    continue
                text = paragraph_text(node)
                if text.strip():
                    yield {"part": part, "paragraph_index": index, "text": text}


def identity(text):
    return " ".join(text.split())


def grade_numbered_paragraphs(expected, actual):
    buckets = defaultdict(list)
    for block in actual.get("blocks", []):
        buckets[identity(block.get("text", ""))].append(block)
    passed = 0
    for row in expected:
        matches = buckets[identity(row["text"])]
        occurrence = row.get("occurrence", 0)
        block = matches[occurrence] if occurrence < len(matches) else {}
        passed += bool(block) and all(block.get(k) == row[k] for k in ("type", "level"))
    return {"passed": passed, "total": len(expected)}


def structure_signature(blocks):
    result = []
    for block in blocks:
        row = [block.get("type"), block.get("level"), structure_signature(block.get("children", []))]
        if block.get("table"):
            row.append([[structure_signature(c.get("blocks", [])) for c in cells]
                        for cells in block["table"]["cells"]])
        result.append(row)
    return result
