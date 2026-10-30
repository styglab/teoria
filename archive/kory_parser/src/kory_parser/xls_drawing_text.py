"""Recover surplus BIFF8 TXO run padding without changing xlrd global state."""

import struct

from xlrd.biffh import XL_CONTINUE, XL_WORKSHEET
from xlrd.sheet import MSTxo, Sheet


def _padded_txo(book, data):
    if len(data) < 16:
        raise ValueError("Truncated TXO header")
    flags, rotation, _, chars, run_bytes, font = struct.unpack("<HH6sHHH", data[:16])
    if not chars or not run_bytes or run_bytes % 8:
        raise ValueError("Unsupported TXO lengths")
    pieces = []
    remaining = chars
    while remaining:
        code, size, payload = book.get_record_parts()
        if code != XL_CONTINUE or size < 2 or payload[0] not in (0, 1):
            raise ValueError("Invalid TXO text continuation")
        width = 2 if payload[0] else 1
        if (size - 1) % width:
            raise ValueError("Unaligned TXO text")
        count = (size - 1) // width
        if count > remaining:
            raise ValueError("TXO text exceeds declared length")
        pieces.append(payload[1:].decode("utf-16le" if width == 2 else "latin1"))
        remaining -= count
    runs = bytearray()
    trimmed = False
    while len(runs) < run_bytes:
        code, size, payload = book.get_record_parts()
        if code != XL_CONTINUE or not size:
            raise ValueError("Missing TXO run continuation")
        remaining = run_bytes - len(runs)
        if size > remaining:
            # Recover only a final run record with surplus, non-aligned bytes.
            # Never consume or repair cell records, short runs or aligned extras.
            if size % 8 == 0:
                raise ValueError("Unexpected aligned TXO runs")
            payload = payload[:remaining]
            trimmed = True
        runs.extend(payload)
    if not trimmed:
        raise ValueError("No surplus TXO run padding")
    result = MSTxo()
    result.text = "".join(pieces)
    result.rot = rotation
    result.ifntEmpty = font
    result.fmla = data[16:]
    result.horz_align = (flags & 0x000E) >> 3
    result.vert_align = (flags & 0x0070) >> 6
    result.lock_text = (flags >> 9) & 1
    result.just_last = (flags >> 14) & 1
    result.secret_edit = (flags >> 15) & 1
    result.rich_text_runlist = [struct.unpack_from("<HH", runs, i) for i in range(0, len(runs), 8)]
    if any(offset > chars for offset, _ in result.rich_text_runlist):
        raise ValueError("TXO run offset exceeds text")
    while result.rich_text_runlist and result.rich_text_runlist[-1][0] == chars:
        result.rich_text_runlist.pop()
    return result


class _PaddedDrawingSheet(Sheet):
    def handle_txo(self, data):
        start = self.book._position
        try:
            return super().handle_txo(data)
        except AssertionError:
            failed_position = self.book._position
            self.book._position = start
            try:
                result = _padded_txo(self.book, data)
            except (ValueError, UnicodeDecodeError, struct.error):
                self.book._position = failed_position
                raise AssertionError("Invalid BIFF drawing text") from None
            self.recovered_drawing_text += 1
            return result


def read_value_sheet(book, index):
    """Use xlrd unchanged unless a BIFF8 sheet fails an ancillary assertion."""
    try:
        return book.sheet_by_index(index), 0
    except AssertionError:
        if book.biff_version != 80:
            raise
        book._position = book._sh_abs_posn[index]
        book.getbof(XL_WORKSHEET)
        sheet = _PaddedDrawingSheet(book, book._position, book._sheet_names[index], index)
        sheet.recovered_drawing_text = 0
        sheet.read(book)
        if not sheet.recovered_drawing_text:
            raise
        book._sheet_list[index] = sheet
        return sheet, sheet.recovered_drawing_text
