"""Group measured glyphs into words and lines without opening a PDF.

Clustering and word boundaries adapted from pdfplumber 0.11.10 (MIT).
Only the coordinate operations used by this parser are retained. See NOTICE.
"""

from itertools import groupby
from operator import itemgetter

LIGATURES = dict(zip("ﬀﬁﬂﬃﬄﬅﬆ", ("ff", "fi", "fl", "ffi", "ffl", "st", "st")))


def clusters(items, key, tolerance):
    values = sorted({key(item) for item in items})
    groups, previous, index = {}, None, -1
    for value in values:
        if previous is None or value > previous + tolerance:
            index += 1
        groups[value] = index
        previous = value
    ordered = sorted(items, key=lambda item: groups[key(item)])
    return [list(group) for _, group in groupby(ordered, key=lambda item: groups[key(item)])]


def extract_words(chars, x_tolerance=2, y_tolerance=3, extra_attrs=(), return_chars=False):
    words = []

    def append_word(letters, direction):
        if not letters:
            return
        x0, top = min(c["x0"] for c in letters), min(c["top"] for c in letters)
        x1, bottom = max(c["x1"] for c in letters), max(c["bottom"] for c in letters)
        word = {
            "text": "".join(LIGATURES.get(c["text"], c["text"]) for c in letters),
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "doctop": top + letters[0]["doctop"] - letters[0]["top"],
            "width": x1 - x0,
            "height": bottom - top,
            "upright": letters[0]["upright"],
            "direction": direction,
            **{key: letters[0][key] for key in extra_attrs},
        }
        if return_chars:
            word["chars"] = letters
        if any("layout_top" in c for c in letters):
            word["layout_top"] = min(c.get("layout_top", c["top"]) for c in letters)
        words.append(word)

    def axes(char, direction):
        if direction == "ltr":
            return char["x0"], char["x1"], char["top"]
        if direction == "rtl":
            return -char["x1"], -char["x0"], char["top"]
        if direction == "btt":
            return -char["bottom"], -char["top"], char["x0"]
        return char["top"], char["bottom"], char["x0"]

    key = lambda c: (c["upright"], c.get("text_direction"), *(c[a] for a in extra_attrs))
    for _, grouped in groupby(chars, key=key):
        grouped = list(grouped)
        direction = grouped[0].get("text_direction") or ("ltr" if grouped[0]["upright"] else "ttb")
        horizontal = direction in ("ltr", "rtl")
        line_key = (lambda c: c.get("layout_top", c["top"])) if horizontal else itemgetter("x0")
        for line in clusters(grouped, line_key, y_tolerance if horizontal else x_tolerance):
            letters = []
            word_end = float("-inf")
            for char in sorted(line, key=lambda c: axes(c, direction)[0]):
                if char["text"].isspace():
                    append_word(letters, direction)
                    letters = []
                    word_end = float("-inf")
                    continue
                if letters:
                    a, b, ay = axes(letters[-1], direction)
                    c, _, cy = axes(char, direction)
                    xt, yt = (x_tolerance, y_tolerance) if horizontal else (y_tolerance, x_tolerance)
                    if c < a or c > max(b, word_end) + xt or abs(cy - ay) > yt:
                        append_word(letters, direction)
                        letters = []
                        word_end = float("-inf")
                letters.append(char)
                word_end = max(word_end, axes(char, direction)[1])
            append_word(letters, direction)
    return words


def extract_text(chars, x_tolerance=2, y_tolerance=3):
    words = extract_words(chars, x_tolerance, y_tolerance)
    return "\n".join(
        " ".join(w["text"] for w in line)
        for line in clusters(words, lambda w: w.get("layout_top", w["top"]), y_tolerance)
    )
