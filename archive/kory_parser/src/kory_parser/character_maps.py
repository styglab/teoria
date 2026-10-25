"""Character tables ported from kordoc 4.22.15 / rhwp (MIT). See NOTICE."""

import json
import re
from importlib.resources import files

_TABLES = json.loads(files(__package__).joinpath("character_maps.json").read_text(encoding="utf-8"))
HANCOM_PUA = {int(k): v for k, v in _TABLES["hancom_pua"].items()}
JOHAB_SYMBOLS = {int(k): chr(v) for k, v in _TABLES["johab_symbols"].items()}
_PRIVATE_USE = re.compile("[\ue000-\uf8ff\U000f0000-\U0010ffff]")

_CHO = [-1, -1, *range(19), *([-1] * 11)]
_JUNG = [
    -1,
    -1,
    -1,
    0,
    1,
    2,
    3,
    4,
    -1,
    -1,
    5,
    6,
    7,
    8,
    9,
    10,
    -1,
    -1,
    11,
    12,
    13,
    14,
    15,
    16,
    -1,
    -1,
    17,
    18,
    19,
    20,
    -1,
    -1,
]
_JONG = [
    -1,
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    -1,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    -1,
    -1,
]
_EXTRA = {
    0x81: "“",
    0x82: "”",
    0x83: "‘",
    0x84: "’",
    0x3366: "□",
    0x2BCE: "(인)",
    0x37ED: "═",
    0x301C: "━",
    0x2F00: "□",
    0x2F08: "▪",
    0x2F11: "◦",
    0x2F14: "◦",
    0x2058: "△",
    0x205A: "○",
    0x3062: "“",
    0x3063: "”",
    0x3066: "‧",
    0x3067: "‘",
    0x3068: "’",
    0x30BB: "《",
    0x30BD: "》",
    0x2024: "・",
}


def map_display_text(text: str) -> str:
    """Render Hancom private glyphs while preserving raw text in document blocks."""
    if _PRIVATE_USE.search(text) is None:
        return text

    from .hwp_numbering import format_number

    def enclosed(number):
        return "⓪" if number == 0 else format_number(number, "CIRCLED_DIGIT")

    def tens(code):
        if 0xF0288 <= code <= 0xF0291:
            return code - 0xF0288
        if 0xF02BA <= code <= 0xF02C2:
            return code - 0xF02B9
        return None

    def units(code):
        if 0xF0292 <= code <= 0xF029B:
            return code - 0xF0292
        if 0xF02C3 <= code <= 0xF02CC:
            return code - 0xF02C3
        return None

    out, index = [], 0
    while index < len(text):
        code = ord(text[index])
        t, u = tens(code), units(code)
        next_u = units(ord(text[index + 1])) if index + 1 < len(text) else None
        if t is not None and next_u is not None:
            out.append(enclosed(t * 10 + next_u))
            index += 2
            continue
        out.append(
            enclosed(t)
            if t is not None
            else str(u)
            if u is not None
            else enclosed(code - 0xF02B0)
            if 0xF02B0 <= code <= 0xF02B9
            else HANCOM_PUA.get(code, text[index])
        )
        index += 1
    return "".join(out)


def johab(code: int) -> str:
    if code < 128 or 0xA0 <= code <= 0xFF:
        return chr(code)
    if code >= 0x8000:
        cho, jung, jong = _CHO[(code >> 10) & 31], _JUNG[(code >> 5) & 31], _JONG[code & 31]
        if ((code >> 5) & 31) == 30 and jong >= 0 and (cho >= 0 or ((code >> 10) & 31) == 1):
            return (chr(0x1100 + cho) if cho >= 0 else "") + "ᆞ" + (chr(0x11A7 + jong) if jong else "")
        if min(cho, jung, jong) >= 0:
            return chr(0xAC00 + cho * 588 + jung * 28 + jong)
        return JOHAB_SYMBOLS.get(code, "\ufffd")
    if code in _EXTRA:
        return _EXTRA[code]
    if 0x3590 <= code <= 0x3599:
        return chr(0x2160 + code - 0x3590)
    if 0x36E7 <= code <= 0x36F0:
        return chr(0x2460 + code - 0x36E7)
    if 0x37C0 <= code <= 0x37C5:
        return "한글과컴퓨터"[code - 0x37C0]
    if code in (0x2010, 0x2013, 0x2014, 0x2103, 0x2113, 0x2190, 0x2192, 0x2193, 0x203B, 0x2022):
        return chr(code)
    if 0x3401 <= code < 0x3401 + 96 * 12:
        index = code - 0x3401
        row, col = 0xA1 + index // 96, 0xA1 + index % 96
    elif 0x4000 <= code < 0x4000 + 94 * 52:
        index = code - 0x4000
        row, col = 0xCA + index // 94, 0xA1 + index % 94
    else:
        return "\ufffd"
    try:
        return bytes((row, col)).decode("euc_kr").replace("∼", "～").replace("⊙", "◉")
    except UnicodeDecodeError:
        return "\ufffd"
