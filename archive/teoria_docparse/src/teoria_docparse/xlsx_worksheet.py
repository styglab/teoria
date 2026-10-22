"""Read worksheet XML while discarding cells that contain only formatting.

Byte expansion and depth remain bounded. The XML node budget applies to the
retained worksheet data; empty styled cells do not require a full DOM in memory.
"""

import io

from defusedxml import ElementTree

from .document_io import local_name
from .models import ParseError, ParseOptions


def worksheet_xml(data: bytes, options: ParseOptions):
    stack = []
    retained = 0
    parser = ElementTree.iterparse(io.BytesIO(data), events=("start", "end"))
    for event, node in parser:
        if event == "start":
            if len(stack) > options.max_depth * 8:
                raise ParseError("RESOURCE_LIMIT", "Worksheet XML nesting exceeds budget")
            stack.append(node)
            continue
        retained += 1
        tag = local_name(node.tag)
        empty_cell = tag == "c" and not any(
            local_name(child.tag) == "f" or local_name(child.tag) in ("v", "t") and child.text
            for child in node.iter()
        )
        if len(stack) > 1 and (empty_cell or tag == "row" and not len(node)):
            retained -= sum(1 for _ in node.iter())
            stack[-2].remove(node)
            node.clear()
        if retained > options.max_xml_nodes:
            raise ParseError("RESOURCE_LIMIT", "Retained worksheet XML exceeds node budget")
        stack.pop()
    return parser.root
