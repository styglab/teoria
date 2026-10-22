"""HWP5 record tree reader. Layout/page approximation is explicit in the result.

Record/control consumption and addressed cell assembly adapted from kordoc 4.22.15
(MIT, chrisryugj; algorithms also derived there from rhwp, MIT, edwardkim).
"""

from __future__ import annotations

import base64
import io
import re
import struct
from dataclasses import dataclass

import olefile

from .character_maps import map_display_text
from .document_io import inflate
from .hwp_numbering import NUMBER_FORMATS, HwpDocInfo, format_number
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


@dataclass(frozen=True)
class Record:
    tag: int
    level: int
    data: bytes
    offset: int


def read_records(data: bytes) -> list[Record]:
    records = []
    offset = 0
    while offset < len(data):
        start = offset
        if offset + 4 > len(data):
            raise ParseError("INVALID_FILE", "Truncated HWP record header")
        header = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        size = header >> 20
        if size == 0xFFF:
            if offset + 4 > len(data):
                raise ParseError("INVALID_FILE", "Truncated HWP extended record header")
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        if offset + size > len(data):
            raise ParseError("INVALID_FILE", "Truncated HWP record payload")
        records.append(Record(header & 0x3FF, (header >> 10) & 0x3FF, data[offset : offset + size], start))
        offset += size
        if len(records) > 500_000:
            raise ParseError("RESOURCE_LIMIT", "Too many HWP records")
    return records


def hwp_text(
    data: bytes, inline_values: dict[str, list[str]] | None = None, field_guides: list[str] | None = None
) -> str:
    """Consume extended controls as 16-byte units, line breaks as 2-byte units."""
    out = []
    values = {k: list(v) for k, v in (inline_values or {}).items()}
    fields = []
    offset = 0
    while offset + 2 <= len(data):
        code = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        if code >= 32:
            if 0xD800 <= code <= 0xDBFF and offset + 2 <= len(data):
                low = struct.unpack_from("<H", data, offset)[0]
                if 0xDC00 <= low <= 0xDFFF:
                    code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
                    offset += 2
            if 0xA000 <= code <= 0xA48C:
                code += 0xE6000
            out.append(chr(code))
        elif code == 10 or code == 0:
            out.append("\n")
        elif code in (13, 24):
            pass
        elif code in (30, 31):
            out.append(" ")
        elif code <= 23:
            if offset + 14 > len(data):
                raise ParseError("INVALID_FILE", "Truncated HWP inline control")
            if code == 9:
                out.append("\t")
            elif code == 3:
                fields.append(len(out))
            elif code == 4 and fields:
                start = fields.pop()
                if "".join(out[start:]).rstrip() in (field_guides or []):
                    del out[start:]
            else:
                control = control_name(data[offset : offset + 4])
                if values.get(control):
                    out.append(values[control].pop(0))
            offset += 14
    return "".join(out).strip()


def control_name(data: bytes) -> str:
    known = {
        "tbl",
        "gso",
        "head",
        "foot",
        "fn",
        "en",
        "eqed",
        "tcmt",
        "tcps",
        "secd",
        "cold",
        "atno",
        "nwno",
        "pgnp",
        "pghd",
        "pgct",
        "bokm",
    }
    reverse = data.decode("ascii", errors="replace")[::-1].strip()
    direct = reverse[::-1].strip()
    return direct if direct in known or direct.startswith("%") else reverse


class Hwp5Parser:
    def __init__(
        self,
        records: list[Record],
        part: str,
        options: ParseOptions,
        result: ParseResult,
        doc_info: HwpDocInfo | None = None,
    ):
        self.records, self.part, self.options, self.result = records, part, options, result
        self.table_number = 0
        self.doc_info = doc_info or HwpDocInfo()

    def end(self, start: int, limit: int) -> int:
        level = self.records[start].level
        index = start + 1
        while index < limit and self.records[index].level > level:
            index += 1
        return index

    def ref(self, index: int) -> SourceRef:
        return SourceRef(self.part, f"record:{index}@{self.records[index].offset}")

    def paragraphs(self, start: int, end: int, depth: int = 0) -> list[Block]:
        if depth > self.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "HWP nesting exceeds budget")
        blocks = []
        index = start
        while index < end:
            record = self.records[index]
            if record.tag == 0x42:
                stop = self.end(index, end)
                blocks.extend(self.paragraph(index, stop, depth + 1))
                index = stop
            else:
                index += 1
        return blocks

    def paragraph(self, start: int, end: int, depth: int) -> list[Block]:
        text = ""
        text_records = []
        values = {}
        guides = []
        objects = []
        index = start + 1
        direct_level = self.records[start].level + 1
        while index < end:
            record = self.records[index]
            if record.tag == 0x43 and record.level == direct_level:
                text_records.append(record.data)
            elif record.tag == 0x47 and record.level == direct_level:
                stop = self.end(index, end)
                control = control_name(record.data[:4])
                if control.strip() == "tbl":
                    objects.append(self.table(index, stop, depth + 1))
                    if len(record.data) >= 8 and struct.unpack_from("<I", record.data, 4)[0] & 1:
                        values.setdefault(control, []).append("\ufffc")
                elif control in ("head", "foot"):
                    nested = self.paragraphs(index + 1, stop, depth + 1)
                    value = plain_text([b for b in nested if b.type != "image"])
                    key = control + ":" + value
                    if value and key not in self.doc_info.page_texts:
                        self.doc_info.page_texts.add(key)
                        target = (
                            self.doc_info.header_blocks if control == "head" else self.doc_info.footer_blocks
                        )
                        target.append(Block("paragraph", value, source=self.ref(index)))
                elif control.strip() in ("gso", "fn", "en"):
                    nested = self.paragraphs(index + 1, stop, depth + 1)
                    objects.extend(nested)
                    if control == "gso":
                        picture_end = next(
                            (n for n in range(index + 1, stop) if self.records[n].tag == 0x48), stop
                        )
                        for n in range(index + 1, picture_end):
                            data = self.records[n].data
                            if self.records[n].tag != 0x55 or len(data) < 73:
                                continue
                            bin_id = struct.unpack_from("<H", data, 71)[0]
                            if not bin_id:
                                continue
                            storage_id, extension = (
                                self.doc_info.bin_data[bin_id - 1]
                                if bin_id <= len(self.doc_info.bin_data)
                                else (bin_id, "")
                            )
                            name = self.doc_info.bin_files.get(storage_id, "")
                            extension = name.rsplit(".", 1)[-1] if "." in name else extension or "bin"
                            if storage_id not in self.doc_info.image_names:
                                self.doc_info.image_names[storage_id] = (
                                    f"image_{len(self.doc_info.image_names) + 1:03d}.{extension.lower()}"
                                )
                            ref = self.ref(n)
                            objects.append(Block("image", self.doc_info.image_names[storage_id], source=ref))
                            self.result.warnings.append(
                                Diagnostic(
                                    "UNEXTRACTED_IMAGE_TEXT", "HWP drawing image text not extracted", ref
                                )
                            )
                elif control.strip() == "eqed":
                    for equation in self.records[index + 1 : stop]:
                        if equation.tag == 0x58 and len(equation.data) >= 6:
                            size = struct.unpack_from("<H", equation.data, 4)[0]
                            script = equation.data[6 : 6 + size * 2].decode("utf-16le", errors="replace")
                            text += script
                            self.result.warnings.append(
                                Diagnostic(
                                    "FORMULA_SOURCE_ONLY", "HWP equation source retained", self.ref(index)
                                )
                            )
                elif control == "tcps" and len(record.data) >= 6:
                    count = struct.unpack_from("<H", record.data, 4)[0]
                    if count and len(record.data) >= 6 + 2 * count:
                        composed = record.data[6 : 6 + 2 * count].decode("utf-16le", errors="replace")
                        enclosed = record.data[6 + 2 * count] if len(record.data) > 6 + 2 * count else 0
                        value = (
                            format_number(int(composed), "CIRCLED_DIGIT")
                            if enclosed and composed.isdecimal() and 1 <= len(composed) <= 2 and int(composed)
                            else "⓪"
                            if enclosed and composed == "0"
                            else map_display_text(composed)
                        )
                        values.setdefault(control, []).append(value)
                elif control.strip() == "atno" and len(record.data) >= 8:
                    flags = struct.unpack_from("<I", record.data, 4)[0]
                    number_type, number_format = flags & 15, (flags >> 4) & 255
                    number = self.doc_info.auto_counters.get(number_type, 1)
                    self.doc_info.auto_counters[number_type] = number + 1
                    adornments = [
                        struct.unpack_from("<H", record.data, offset)[0]
                        if len(record.data) >= offset + 2
                        else 0
                        for offset in (12, 14)
                    ]
                    fmt = {6: "HANGUL_SYLLABLE"}.get(
                        number_format, NUMBER_FORMATS.get(number_format, "DIGIT")
                    )
                    value = (
                        (chr(adornments[0]) if adornments[0] else "")
                        + format_number(number, fmt)
                        + (chr(adornments[1]) if adornments[1] else "")
                    )
                    values.setdefault(control, []).append(value)
                elif control.strip() == "nwno" and len(record.data) >= 10:
                    number_type = struct.unpack_from("<I", record.data, 4)[0] & 15
                    self.doc_info.auto_counters[number_type] = (
                        struct.unpack_from("<H", record.data, 8)[0] or 1
                    )
                elif control == "%clk" and len(record.data) >= 11:
                    flags = struct.unpack_from("<I", record.data, 4)[0]
                    size = struct.unpack_from("<H", record.data, 9)[0]
                    command = record.data[11 : 11 + size * 2].decode("utf-16le", errors="replace")
                    match = re.search(r"Direction:wstring:(\d+):", command)
                    if not flags & (1 << 15) and match:
                        guides.append(command[match.end() : match.end() + int(match[1])])
                elif control.strip() == "secd" and len(record.data) >= 20:
                    self.doc_info.outline_id = struct.unpack_from("<H", record.data, 18)[0]
                elif control.strip() not in (
                    "tcmt",
                    "secd",
                    "cold",
                    "atno",
                    "nwno",
                    "pgnp",
                    "pgct",
                    "bokm",
                ) and not control.startswith("%"):
                    self.result.warnings.append(
                        Diagnostic(
                            "UNHANDLED_CONTROL", f"HWP control {control!r} not interpreted", self.ref(index)
                        )
                    )
                index = stop
                continue
            index += 1
        text = hwp_text(b"".join(text_records), values, guides) + text
        shape_id = (
            struct.unpack_from("<H", self.records[start].data, 8)[0]
            if len(self.records[start].data) >= 10
            else -1
        )
        prefix, heading_level = self.doc_info.heading(shape_id)
        if prefix and text.strip():
            text = prefix + " " + text
        # The object placeholder establishes order for inline tables; floating objects follow text.
        output = []
        fragments = text.split("\ufffc")
        for n, fragment in enumerate(fragments):
            if fragment.strip() or (
                len(fragments) == 1 and not objects and self.options.keep_empty_paragraphs
            ):
                output.append(
                    Block(
                        "heading" if heading_level else "paragraph",
                        fragment.strip(),
                        level=heading_level,
                        source=self.ref(start),
                    )
                )
            if n < len(fragments) - 1 and objects:
                obj = objects.pop(0)
                obj.inline_continuation = bool(output)
                output.append(obj)
                # The following paragraph fragment belongs to the same text line.
                if n + 1 < len(fragments) and fragments[n + 1].strip():
                    continuation = Block(
                        "paragraph",
                        fragments[n + 1].strip(),
                        source=self.ref(start),
                        inline_continuation=True,
                    )
                    output.append(continuation)
                    fragments[n + 1] = ""
        output.extend(objects)
        return output

    def table(self, start: int, end: int, depth: int) -> Block:
        if depth > self.options.max_depth:
            raise ParseError("RESOURCE_LIMIT", "HWP table nesting exceeds budget")
        level = self.records[start].level + 1
        table_index = next(
            (
                i
                for i in range(start + 1, end)
                if self.records[i].tag == 0x4D
                and self.records[i].level == level
                and len(self.records[i].data) >= 8
            ),
            None,
        )
        if table_index is None:
            raise ParseError("INVALID_TABLE", "HWP table has no table definition")
        rows, cols = struct.unpack_from("<HH", self.records[table_index].data, 4)
        addressed = []
        index = table_index + 1
        while index < end:
            record = self.records[index]
            if record.tag != 0x48:
                index += 1
                continue
            stop = index + 1
            while stop < end:
                other = self.records[stop]
                if other.level < record.level or (other.level == record.level and other.tag in (0x48, 0x4D)):
                    break
                stop += 1
            if len(record.data) < 16:
                raise ParseError("INVALID_TABLE", "HWP table cell has no address")
            col, row, cs, rs = struct.unpack_from("<HHHH", record.data, 8)
            cs, rs = max(1, cs), max(1, rs)
            nested = self.paragraphs(index + 1, stop, depth + 1)
            structured = any(b.type in ("table", "image") for b in nested)
            cell = Cell(
                plain_text(nested),
                rs,
                cs,
                nested if structured else [],
                self.ref(index),
                bool(struct.unpack_from("<H", record.data, 6)[0] & 4),
            )
            addressed.append((row, col, cell))
            rows, cols = max(rows, row + rs), max(cols, col + cs)
            index = stop
        self.table_number += 1
        table = table_from_cells(rows, cols, addressed, self.options, f"{self.part}:table:{start}")
        if any(r.tag == 0x48 for r in self.records[start + 1 : table_index]):
            table.caption = plain_text(self.paragraphs(start + 1, table_index, depth + 1))
        return Block("table", table=table, source=self.ref(start))


def parse_hwp(data: bytes, options: ParseOptions) -> ParseResult:
    result = ParseResult(True, "hwp", page_mode="section")
    with olefile.OleFileIO(io.BytesIO(data)) as archive:
        if not archive.exists("FileHeader"):
            raise ParseError("INVALID_FILE", "HWP FileHeader missing")
        header = archive.openstream("FileHeader").read()
        if len(header) < 40 or not header.startswith(b"HWP Document File\x00"):
            raise ParseError("INVALID_FILE", "Invalid HWP header")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & (2 | 16):
            raise ParseError("ENCRYPTED", "Encrypted or DRM-protected HWP is not supported")
        if flags & 4:
            raise ParseError(
                "UNSUPPORTED_ENCRYPTION", "Distribution-protected HWP decryption is not yet ported"
            )
        sections = sorted(
            (
                p
                for p in archive.listdir()
                if len(p) == 2 and p[0] == "BodyText" and re.fullmatch(r"Section\d+", p[1])
            ),
            key=lambda p: int(p[1][7:]),
        )
        if not sections:
            raise ParseError("INVALID_FILE", "HWP body missing")
        expanded = 0
        doc_info = HwpDocInfo()
        if archive.exists("DocInfo"):
            info_data = archive.openstream("DocInfo").read()
            if flags & 1:
                info_data = inflate(info_data, options)
            expanded += len(info_data)
            doc_info = HwpDocInfo.from_records(read_records(info_data))
        for path in archive.listdir():
            if len(path) == 2 and path[0] == "BinData":
                match = re.match(r"BIN([0-9a-fA-F]+)\.", path[1])
                if match:
                    doc_info.bin_files[int(match[1], 16)] = "/".join(path)
        for index, path in enumerate(sections, 1):
            if options.pages is not None and index not in options.pages:
                continue
            body = archive.openstream(path).read()
            if flags & 1:
                body = inflate(body, options)
            expanded += len(body)
            if expanded > options.max_expanded_bytes:
                raise ParseError("RESOURCE_LIMIT", "HWP streams exceed expansion budget")
            records = read_records(body)
            result.blocks.extend(
                Hwp5Parser(records, "/".join(path), options, result, doc_info).paragraphs(0, len(records))
            )
        if options.images:
            for path in archive.listdir():
                if path[0] == "BinData":
                    image = archive.openstream(path).read()
                    result.blocks.append(
                        Block(
                            "image",
                            source=SourceRef("/".join(path)),
                            image_data=base64.b64encode(image).decode(),
                        )
                    )
        result.blocks = [*doc_info.header_blocks, *result.blocks, *doc_info.footer_blocks]
        result.page_count = len(sections)
        result.metadata["version"] = ".".join(str(b) for b in reversed(header[32:36]))
        result.warnings.append(
            Diagnostic("SECTION_PAGES", "HWP page ranges refer to sections, not rendered pages")
        )
    return result
