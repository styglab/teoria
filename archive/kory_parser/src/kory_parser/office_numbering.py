"""WordprocessingML paragraph style inheritance and automatic list numbering."""

import re

from .character_maps import map_display_text
from .document_io import local_name
from .hangul_xml import attr, first
from .hwp_numbering import format_number
from .models import ParseError


def child(node, name):
    return next((n for n in node if local_name(n.tag) == name), None) if node is not None else None


def value(node, name, default=None):
    item = child(node, name)
    return attr(item, "val", default) if item is not None else default


class DocxNumbering:
    def __init__(self, archive, max_depth):
        self.max_depth = max_depth
        self.styles, self.abstract, self.numbers, self.counters = {}, {}, {}, {}
        if "word/styles.xml" in archive.names:
            self.styles = {
                attr(n, "styleId"): n for n in archive.xml("word/styles.xml") if local_name(n.tag) == "style"
            }
        if "word/numbering.xml" not in archive.names:
            return
        for node in archive.xml("word/numbering.xml"):
            if local_name(node.tag) == "abstractNum":
                self.abstract[attr(node, "abstractNumId")] = {
                    int(attr(n, "ilvl")): n for n in node if local_name(n.tag) == "lvl"
                }
            elif local_name(node.tag) == "num":
                self.numbers[attr(node, "numId")] = (
                    value(node, "abstractNumId"),
                    {int(attr(n, "ilvl")): n for n in node if local_name(n.tag) == "lvlOverride"},
                )

    def properties(self, paragraph):
        properties, ancestors = {}, []
        current = value(child(paragraph, "pPr"), "pStyle")
        seen = set()
        while current in self.styles:
            if current in seen or len(seen) >= self.max_depth:
                raise ParseError("INVALID_FILE", "Cyclic or oversized paragraph style inheritance")
            seen.add(current)
            node = self.styles[current]
            ancestors.append(child(node, "pPr"))
            current = value(node, "basedOn")
        for node in [*reversed(ancestors), child(paragraph, "pPr")]:
            for name in ("outlineLvl",):
                resolved = value(node, name)
                if resolved is not None:
                    properties[name] = int(resolved)
            numbering = child(node, "numPr")
            for name in ("numId", "ilvl"):
                resolved = value(numbering, name)
                if resolved is not None:
                    properties[name] = resolved
        return properties

    def level(self, number_id, index):
        abstract_id, overrides = self.numbers[number_id]
        override = overrides.get(index)
        definition = child(override, "lvl")
        if definition is None:
            definition = self.abstract.get(abstract_id, {}).get(index)
        if definition is None:
            return None
        start = int(value(override, "startOverride", value(definition, "start", "1")))
        restart = int(value(definition, "lvlRestart", str(index)))
        restart = min(restart, index)
        return {
            "start": start,
            "restart": restart,
            "format": value(definition, "numFmt", "decimal"),
            "text": value(definition, "lvlText", "%" + str(index + 1) + "."),
            "suffix": value(definition, "suff", "tab"),
            "legal": child(definition, "isLgl") is not None,
            "font": attr(first(definition, "rFonts"), "ascii")
            if first(definition, "rFonts") is not None
            else "",
        }

    def prefix(self, properties):
        number_id, index = properties.get("numId"), int(properties.get("ilvl", "0"))
        if number_id in (None, "0"):
            return "", None, None
        if not 0 <= index <= 8 or number_id not in self.numbers:
            return "", index + 1, "UNRESOLVED_DOCX_NUMBERING"
        level = self.level(number_id, index)
        if level is None:
            return "", index + 1, "UNRESOLVED_DOCX_NUMBERING"
        state = self.counters.setdefault(number_id, {})
        state[index] = state.get(index, level["start"] - 1) + 1
        for lower in list(state):
            if lower > index:
                definition = self.level(number_id, lower)
                if definition and definition["restart"] and index <= definition["restart"] - 1:
                    del state[lower]
        unsupported = False

        def number(match):
            nonlocal unsupported
            position = int(match[1]) - 1
            definition = self.level(number_id, position)
            if definition is None or position > index:
                return ""
            current = state.get(position, definition["start"])
            kind = "decimal" if level["legal"] else definition["format"]
            if kind in ("upperLetter", "lowerLetter"):
                text = ""
                while current > 0:
                    current, remainder = divmod(current - 1, 26)
                    text = chr(65 + remainder) + text
                return text.lower() if kind == "lowerLetter" else text
            formats = {
                "decimal": "DIGIT",
                "upperRoman": "ROMAN_CAPITAL",
                "lowerRoman": "ROMAN_SMALL",
                "decimalEnclosedCircle": "CIRCLED_DIGIT",
            }
            # Only the verified basic Ganada order; retain warnings outside it.
            if kind == "ganada" and 1 <= current <= 14:
                return format_number(current, "HANGUL_SYLLABLE")
            if kind == "decimalZero":
                return f"{current:02d}"
            if kind not in formats:
                unsupported = True
                return match[0]
            return format_number(current, formats[kind])

        if level["format"] == "none":
            text = ""
        elif level["format"] == "bullet":
            text = (
                "•"
                if level["font"] == "Symbol" and level["text"] == "\uf0b7"
                else map_display_text(level["text"])
            )
        else:
            text = re.sub(r"%([1-9])", number, level["text"])
        suffix = "" if level["suffix"] == "nothing" else " "
        return (
            text + suffix if text else "",
            index + 1,
            "UNSUPPORTED_DOCX_NUMBER_FORMAT" if unsupported else None,
        )
