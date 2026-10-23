"""HWP/HWPX numbering definitions and display rules, ported from kordoc/rhwp (MIT)."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field


def format_number(number: int, kind: str) -> str:
    if kind == "DIGIT":
        return str(number)
    n = max(1, number) - 1
    if kind == "CIRCLED_DIGIT":
        return (
            chr(0x2460 + n)
            if n < 20
            else chr(0x3251 + n - 20)
            if n < 35
            else chr(0x32B1 + n - 35)
            if n < 50
            else f"({number})"
        )
    if kind == "CIRCLED_HANGUL_SYLLABLE" and n < 14:
        return chr(0x326E + n)
    if kind in ("HANGUL_SYLLABLE", "CIRCLED_HANGUL_SYLLABLE"):
        initials = (0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18)
        vowels = (0, 4, 8, 13, 18, 20)
        return chr(0xAC00 + initials[n % 14] * 588 + vowels[min(n // 14, 5)] * 28)
    if kind == "HANGUL_JAMO":
        return "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"[n % 14]
    if kind == "CIRCLED_HANGUL_JAMO":
        return chr(0x3260 + n % 14)
    if kind in ("LATIN_CAPITAL", "LATIN_SMALL"):
        return chr((65 if kind == "LATIN_CAPITAL" else 97) + n % 26)
    if kind in ("ROMAN_CAPITAL", "ROMAN_SMALL"):
        if not 0 < number <= 3999:
            return str(number)
        text = ""
        for value, symbol in (
            (1000, "M"),
            (900, "CM"),
            (500, "D"),
            (400, "CD"),
            (100, "C"),
            (90, "XC"),
            (50, "L"),
            (40, "XL"),
            (10, "X"),
            (9, "IX"),
            (5, "V"),
            (4, "IV"),
            (1, "I"),
        ):
            count, number = divmod(number, value)
            text += symbol * count
        return text.lower() if kind == "ROMAN_SMALL" else text
    return str(number)


NUMBER_FORMATS = {
    0: "DIGIT",
    1: "CIRCLED_DIGIT",
    2: "ROMAN_CAPITAL",
    3: "ROMAN_SMALL",
    4: "LATIN_CAPITAL",
    5: "LATIN_SMALL",
    8: "HANGUL_SYLLABLE",
    9: "CIRCLED_HANGUL_SYLLABLE",
    10: "HANGUL_JAMO",
    11: "CIRCLED_HANGUL_JAMO",
}


@dataclass
class Numbering:
    formats: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    starts: list[int] = field(default_factory=lambda: [1] * 7)


class NumberingState:
    def __init__(self):
        self.current = 0
        self.counters = [0] * 7
        self.history = {}

    def prefix(self, number_id: int, level: int, definition: Numbering) -> str:
        level = min(level, 6)
        if self.current != number_id:
            if self.current:
                self.history[self.current] = self.counters[:]
            self.counters = self.history.get(number_id, self.counters[:level] + [0] * (7 - level))[:]
            self.current = number_id
        self.counters[level] += 1
        self.counters[level + 1 :] = [0] * (6 - level)
        fmt = definition.formats[level] if level < len(definition.formats) else ""

        def replace(match):
            index = int(match[1]) - 1
            return format_number(
                definition.starts[index] - 1 + self.counters[index]
                if self.counters[index]
                else definition.starts[index],
                definition.kinds[index],
            )

        return re.sub(r"\^(?![^\W_])", "", re.sub(r"\^([1-7])", replace, fmt)).strip()


@dataclass
class HwpDocInfo:
    para_shapes: list[tuple[int, int, int]] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    numberings: list[Numbering] = field(default_factory=list)
    state: NumberingState = field(default_factory=NumberingState)
    auto_counters: dict[int, int] = field(default_factory=dict)
    outline_id: int = 0
    header_blocks: list = field(default_factory=list)
    footer_blocks: list = field(default_factory=list)
    page_texts: set[str] = field(default_factory=set)
    bin_data: list[tuple[int, str]] = field(default_factory=list)
    bin_files: dict[int, str] = field(default_factory=dict)
    image_names: dict[int, str] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records):
        doc = cls()
        for record in records:
            data = record.data
            if record.tag == 0x12 and len(data) >= 4:
                kind, storage_id = struct.unpack_from("<HH", data)
                size = struct.unpack_from("<H", data, 4)[0] if len(data) >= 6 else 0
                extension = data[6 : 6 + size * 2].decode("utf-16le", errors="replace")
                doc.bin_data.append((storage_id if kind & 15 else 0, extension))
            elif record.tag == 0x19 and len(data) >= 32:
                flags = struct.unpack_from("<I", data)[0]
                doc.para_shapes.append(
                    ((flags >> 23) & 3, (flags >> 25) & 7, struct.unpack_from("<H", data, 30)[0])
                )
            elif record.tag == 0x18 and len(data) >= 14:
                doc.bullets.append(chr(struct.unpack_from("<H", data, 12)[0]))
            elif record.tag == 0x17:
                offset, definition = 0, Numbering()
                for _ in range(7):
                    if offset + 14 > len(data):
                        definition.formats.append("")
                        definition.kinds.append("DIGIT")
                        continue
                    flags = struct.unpack_from("<I", data, offset)[0]
                    size = struct.unpack_from("<H", data, offset + 12)[0]
                    offset += 14
                    definition.formats.append(data[offset : offset + size * 2].decode("utf-16le"))
                    definition.kinds.append(NUMBER_FORMATS.get((flags >> 5) & 15, "DIGIT"))
                    offset += size * 2
                base = struct.unpack_from("<H", data, offset)[0] or 1 if offset + 2 <= len(data) else 1
                offset += 2
                definition.starts = [
                    struct.unpack_from("<I", data, offset + i * 4)[0] or 1
                    if offset + (i + 1) * 4 <= len(data)
                    else base
                    for i in range(7)
                ]
                doc.numberings.append(definition)
        return doc

    def heading(self, shape_id: int) -> tuple[str, int | None]:
        if not 0 <= shape_id < len(self.para_shapes):
            return "", None
        kind, level, number_id = self.para_shapes[shape_id]
        if kind == 3 and 0 < number_id <= len(self.bullets):
            bullet = self.bullets[number_id - 1]
            return (bullet if bullet != "\uffff" else ""), None
        if kind in (1, 2):
            number_id = number_id or (self.outline_id if kind == 1 else 0)
            prefix = (
                self.state.prefix(number_id, level, self.numberings[number_id - 1])
                if 0 < number_id <= len(self.numberings)
                else ""
            )
            return prefix, min(level + 1, 6) if kind == 1 else None
        return "", None
