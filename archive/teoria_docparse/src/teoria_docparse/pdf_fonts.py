"""Recover Unicode only from explicit font mappings or reviewed exact outlines."""

import hashlib
import io
import json
import re
from importlib.resources import files

from fontTools import agl
from fontTools.ttLib import TTFont, TTLibError

GLYPH_MAPS = json.loads(files(__package__).joinpath("pdf_glyph_maps.json").read_text(encoding="utf-8"))[
    "families"
]


def family(name):
    name = re.sub(r"^[A-Z]{6}\+", "", name).split("-WinCharSet", 1)[0]
    try:
        return name.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def outline_signature(font, glyph_name):
    """Include every contour point, on-curve flag and units-per-em in the digest."""
    if "glyf" not in font:
        return None
    glyphs = font["glyf"]
    coordinates, ends, flags = glyphs[glyph_name].getCoordinates(glyphs)
    if len(coordinates) > 400 or len(ends) > 8:
        return None
    contours, start = [], 0
    for end in ends:
        contours.append(
            [
                [int(x), int(y), bool(flags[i] & 1)]
                for i, (x, y) in enumerate(coordinates[start : end + 1], start)
            ]
        )
        start = end + 1
    return hashlib.sha256(
        json.dumps([font["head"].unitsPerEm, contours], separators=(",", ":")).encode()
    ).hexdigest()


def glyph_text(font, gid, face):
    order = font.getGlyphOrder()
    if not 0 < gid < len(order):
        return None
    name = order[gid]
    if "glyf" in font and font["glyf"][name].numberOfContours == 0:
        return " "
    cmap = font.getBestCmap() if "cmap" in font else {}
    codes = {
        code
        for code, glyph in (cmap or {}).items()
        if glyph == name and chr(code).isprintable() and not 0xE000 <= code <= 0xF8FF
    }
    if len(codes) == 1:
        return chr(next(iter(codes)))
    named = agl.toUnicode(name)
    if named and named.isprintable():
        return named
    return GLYPH_MAPS.get(face, {}).get(outline_signature(font, name))


def glyph_replacements(native, raw):
    unknown = {
        (span["font"], tuple(c["origin"]))
        for b in raw["blocks"]
        for line in b.get("lines", [])
        for span in line["spans"]
        for c in span["chars"]
        if c["c"] == "\ufffd"
    }
    if not unknown:
        return {}
    fonts = {}
    for entry in native.get_fonts(full=True):
        fonts.setdefault(family(entry[3]), []).append(entry[0])
    cache = getattr(native.parent, "_kordoc_glyph_text", {})
    native.parent._kordoc_glyph_text = cache
    resolved = {}
    for span in native.get_texttrace():
        face = family(span["font"])
        needed = [
            (gid, tuple(origin))
            for code, gid, origin, _ in span["chars"]
            if code == 65533 and (span["font"], tuple(origin)) in unknown
        ]
        for gid, origin in needed:
            key = (face, tuple(fonts.get(face, [])), gid)
            if key not in cache:
                candidates = set()
                for xref in fonts.get(face, []):
                    try:
                        with TTFont(io.BytesIO(native.parent.extract_font(xref)[3]), lazy=True) as font:
                            candidates.add(glyph_text(font, gid, face))
                    except (KeyError, ValueError, IndexError, OSError, TTLibError):
                        candidates.add(None)
                cache[key] = next(iter(candidates)) if len(candidates) == 1 else None
            if cache[key] is not None:
                resolved[(span["font"], origin)] = cache[key]
    return resolved
