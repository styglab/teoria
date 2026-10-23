"""HWP3 stream/control reader adapted from kordoc/rhwp (MIT; see NOTICE)."""

from __future__ import annotations

import struct

from .character_maps import johab
from .document_io import inflate
from .models import (
    Block,
    Cell,
    Diagnostic,
    ParseError,
    ParseOptions,
    ParseResult,
    SourceRef,
    plain_text,
    table_from_cells,
)


class Reader:
    def __init__(self, data: bytes):
        self.data, self.position = data, 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.position + size > len(self.data):
            raise ParseError("INVALID_FILE", "Truncated HWP3 stream")
        data = self.data[self.position : self.position + size]
        self.position += size
        return data

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]


class Hwp3Parser:
    def __init__(self, reader: Reader, options: ParseOptions, result: ParseResult):
        self.reader, self.options, self.result = reader, options, result

    def paragraphs(self, depth=0) -> list[Block]:
        if depth > min(16, self.options.max_depth):
            raise ParseError("RESOURCE_LIMIT", "HWP3 nesting exceeds budget")
        reader = self.reader
        output = []
        while reader.position < len(reader.data):
            offset = reader.position
            follow, count = reader.u8(), reader.u16()
            if count == 0:
                reader.take(40)
                break
            lines = reader.u16()
            if count > 60_000 or lines > 4096:
                raise ParseError("INVALID_FILE", "Invalid HWP3 paragraph header")
            inline_shapes = reader.u8()
            reader.take(37)
            if not follow:
                reader.take(187)
            reader.take(lines * 14)
            if inline_shapes:
                for _ in range(count):
                    if reader.u8() != 1:
                        reader.take(31)
            text, objects = self.characters(count, depth + 1)
            ref = SourceRef("Body", f"offset:{offset}")
            fragments = text.split("\ufffc")
            for n, fragment in enumerate(fragments):
                if fragment.strip() or (
                    len(fragments) == 1 and not objects and self.options.keep_empty_paragraphs
                ):
                    output.append(Block("paragraph", fragment.strip(), source=ref))
                if n < len(fragments) - 1 and objects:
                    output.append(objects.pop(0))
            output.extend(objects)
        return output

    def characters(self, count: int, depth: int) -> tuple[str, list[Block]]:
        reader = self.reader
        text, objects = [], []
        i = 0
        simple = {
            19: (6, ""),
            20: (6, ""),
            21: (6, ""),
            22: (22, ""),
            23: (8, ""),
            24: (4, "-"),
            25: (4, ""),
            26: (244, ""),
            30: (2, " "),
            31: (2, " "),
        }
        while i < count:
            code = reader.u16()
            i += 1
            if code >= 32:
                text.append(johab(code))
                continue
            if code in (0, 13):
                if code == 13:
                    text.append("\n")
                continue
            if code == 9:
                reader.take(6)
                i += 3
                text.append("\t")
                continue
            if code == 18:
                info = reader.take(6)
                i += 3
                kind, number = struct.unpack_from("<HH", info)
                if kind in (1, 2, 3, 4, 5):
                    text.append(str(number))
                continue
            if code == 28:
                info = reader.take(62)
                i += 31
                level = min(info[3], 6)
                number = struct.unpack_from("<H", info, 4 + level * 2)[0]
                if number:
                    text.append(f"{number}. ")
                self.result.warnings.append(
                    Diagnostic("APPROXIMATE_NUMBERING", "HWP3 outline glyph format not fully ported")
                )
                continue
            if code in simple:
                size, value = simple[code]
                reader.take(size)
                i += size // 2
                text.append(value)
                continue
            size = reader.u32()
            reader.take(2)
            i += 3
            if code == 10:
                objects.append(self.table(depth + 1))
                text.append("\ufffc")
            elif code == 11:
                info = reader.take(348)
                extra = struct.unpack_from("<I", info)[0]
                reader.take(extra)
                objects.append(Block("image", source=SourceRef("Body", f"image:{reader.position}")))
                objects.extend(self.paragraphs(depth + 1))
                self.result.warnings.append(
                    Diagnostic("UNEXTRACTED_IMAGE_TEXT", "HWP3 drawing/image content not fully ported")
                )
            elif code == 14:
                reader.take(84)
            elif code in (15, 16, 17):
                reader.take({15: 8, 16: 10, 17: 14}[code])
                nested = self.paragraphs(depth + 1)
                if code != 15:
                    objects.extend(nested)
            elif code in (5, 29):
                reader.take(size)
            elif code in (6, 7, 8):
                reader.take({6: 34, 7: 76, 8: 88}[code])
            else:
                self.result.warnings.append(Diagnostic("UNHANDLED_CONTROL", f"HWP3 control {code}"))
        return "".join(text), objects

    def table(self, depth: int) -> Block:
        info = self.reader.take(84)
        count = struct.unpack_from("<H", info, 80)[0] or 1
        if count > self.options.max_cells:
            raise ParseError("RESOURCE_LIMIT", "HWP3 cell budget exceeded")
        geometry = self.reader.take(27 * count)
        geo = []
        for n in range(count):
            x, y, w, h = struct.unpack_from("<HHHH", geometry, n * 27 + 4)
            geo.append((x, y, x + w, y + h))
        xs = sorted({g[0] for g in geo} | {max(g[2] for g in geo)})
        ys = sorted({g[1] for g in geo} | {max(g[3] for g in geo)})
        addressed = []
        for n, (x, y, right, bottom) in enumerate(geo):
            body = self.paragraphs(depth + 1)
            next_x = min(
                (g[0] for g in geo if g[0] > x and g[0] >= right - 5 and g[1] < bottom and g[3] > y),
                default=xs[-1],
            )
            next_y = min(
                (g[1] for g in geo if g[1] > y and g[1] >= bottom - 5 and g[0] < right and g[2] > x),
                default=ys[-1],
            )
            row, col = ys.index(y), xs.index(x)
            cell = Cell(
                plain_text(body),
                max(1, ys.index(next_y) - row),
                max(1, xs.index(next_x) - col),
                body if any(b.type in ("table", "image") for b in body) else [],
                SourceRef("Body", f"hwp3-cell:{n}"),
            )
            addressed.append((row, col, cell))
        caption = self.paragraphs(depth + 1)
        table = table_from_cells(len(ys) - 1, len(xs) - 1, addressed, self.options)
        table.caption = plain_text(caption) or None
        return Block("table", table=table)


def parse_hwp3(data: bytes, options: ParseOptions) -> ParseResult:
    if len(data) < 1166:
        raise ParseError("INVALID_FILE", "HWP3 header truncated")
    if struct.unpack_from("<H", data, 30 + 96)[0]:
        raise ParseError("ENCRYPTED", "Password protected HWP3 is not supported")
    length = struct.unpack_from("<H", data, 30 + 126)[0]
    body = data[1166 + length :]
    if data[30 + 124]:
        body = inflate(body, options)
    reader = Reader(body)
    for _ in range(7):
        reader.take(reader.u16() * 40)
    reader.take(reader.u16() * 238)
    result = ParseResult(True, "hwp3")
    for index, name in enumerate(("title", "description", "author", "created_at")):
        chars = struct.unpack_from("<56H", data, 158 + index * 112)
        result.metadata[name] = "".join(
            johab(c) for c in chars[: next((i for i, c in enumerate(chars) if c == 0), 56)]
        )
    if options.pages is not None:
        raise ParseError("UNSUPPORTED_OPTION", "HWP3 has no reliable page boundaries")
    result.blocks = Hwp3Parser(reader, options, result).paragraphs()
    return result
