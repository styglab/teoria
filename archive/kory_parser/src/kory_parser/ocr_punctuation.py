"""Conservative image evidence for single quotes flattened by the OCR alphabet."""

from __future__ import annotations


def curved_quote(image, box):
    """Return a curved quote only for an isolated upper glyph with a clear bulb/tail."""
    xs, ys = zip(*box)
    crop = image.crop((min(xs), min(ys), max(xs), max(ys))).convert("L")
    width, height = crop.size
    if width < 3 or height < 8 or width * height > 40_000:
        return None
    low, high = crop.getextrema()
    if high - low < 50:
        return None
    pixels = crop.load()
    threshold = (low + high) // 2
    remaining = {(x, y) for y in range(height) for x in range(width) if pixels[x, y] < threshold}
    components = []
    while remaining:
        start = remaining.pop()
        component, pending = [start], [start]
        while pending:
            x, y = pending.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    point = (x + dx, y + dy)
                    if point in remaining:
                        remaining.remove(point)
                        component.append(point)
                        pending.append(point)
        xx, yy = zip(*component)
        left, right, top, bottom = min(xx), max(xx), min(yy), max(yy)
        w, h = right - left + 1, bottom - top + 1
        if (
            len(component) >= 6
            and 0 < left
            and right < width - 1
            and top < height * 0.25
            and height * 0.12 <= h <= height * 0.55
            and height * 0.04 <= w <= height * 0.35
            and h >= w * 1.25
        ):
            components.append((abs((left + right) / 2 - width / 2), component, top, h))
    if not components:
        return None
    _, component, top, h = min(components, key=lambda c: c[0])
    third = max(1, h // 3)
    upper = sum(y < top + third for x, y in component)
    lower = sum(y >= top + h - third for x, y in component)
    if lower >= upper * 1.45:
        return "‘"
    if upper >= lower * 1.45:
        return "’"
    return None


def restore_image_quotes(image, result):
    """Preserve words and spacing; never infer quote direction from sentence context."""
    lines = result.txts
    word_lines = getattr(result, "word_results", None)
    if lines is None or not word_lines or len(lines) != len(word_lines):
        return
    restored = []
    for text, words in zip(lines, word_lines):
        if "'" not in text or "".join(w[0] for w in words).replace(" ", "") != text.replace(" ", ""):
            restored.append(text)
            continue
        chars = list(text)
        cursor = 0
        for token, score, box in words:
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if token == "'" and box is not None and cursor < len(chars):
                quote = curved_quote(image, box)
                if quote:
                    chars[cursor] = quote
            cursor += len(token)
        restored.append("".join(chars))
    result.txts = tuple(restored)


def quote_word_boxes(convert, images, boxes, recognition):
    """Adapt RapidOCR's coordinate stage without computing unused character boxes.

    Keep a truthy placeholder per untouched line because RapidOCR's score filter
    otherwise drops empty word entries and loses alignment with text lines.
    """
    from dataclasses import replace

    texts = recognition.txts
    selected = [i for i, text in enumerate(texts) if "'" in text or ("]" in text and "[" not in text)]
    words = [((text, float(score), None),) for text, score in zip(texts, recognition.scores)]
    if selected:
        subset = replace(
            recognition,
            txts=tuple(texts[i] for i in selected),
            scores=[recognition.scores[i] for i in selected],
            word_results=tuple(recognition.word_results[i] for i in selected),
        )
        converted = convert([images[i] for i in selected], boxes[selected], subset)
        for i, line in zip(selected, converted):
            words[i] = line
    return tuple(words)


def _corner_glyph(image, box, opening):
    """Match an isolated L with a single bar; square/rounded brackets stay unchanged."""
    from statistics import median

    xs, ys = zip(*box)
    crop = image.crop((min(xs), min(ys), max(xs), max(ys))).convert("L")
    width, height = crop.size
    if width < 3 or height < 8 or width * height > 40_000:
        return False
    low, high = crop.getextrema()
    if high - low < 50:
        return False
    threshold = (low + high) // 2
    pixels = crop.load()
    remaining = {(x, y) for y in range(height) for x in range(width) if pixels[x, y] < threshold}
    matches = 0
    while remaining:
        start = remaining.pop()
        component, pending = {start}, [start]
        while pending:
            x, y = pending.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    point = (x + dx, y + dy)
                    if point in remaining:
                        remaining.remove(point)
                        component.add(point)
                        pending.append(point)
        xx, yy = zip(*component)
        left, top, right, bottom = min(xx), min(yy), max(xx), max(yy)
        w, h = right - left + 1, bottom - top + 1
        if not (height * 0.12 <= w <= height * 0.6 and height * 0.25 <= h <= height * 0.7 and h >= w * 1.2):
            continue
        if opening and (top > height * 0.25 or bottom >= height * 0.7):
            continue
        if not opening and (top < height * 0.25 or bottom < height * 0.7):
            continue
        v = int(
            median(sum((x, y) in component for x in range(left, right + 1)) for y in range(top, bottom + 1))
        )
        b = int(
            median(sum((x, y) in component for y in range(top, bottom + 1)) for x in range(left, right + 1))
        )
        if not (1 <= v <= w * 0.45 and 1 <= b <= h * 0.4):
            continue
        expected = {
            (x, y)
            for y in range(top, bottom + 1)
            for x in range(left, right + 1)
            if x < left + v or y < top + b
        }
        if not opening:
            expected = {
                (x, y)
                for y in range(top, bottom + 1)
                for x in range(left, right + 1)
                if x > right - v or y > bottom - b
            }
        if len(expected & component) / len(expected | component) >= 0.90:
            matches += 1
    return matches == 1


def restore_image_corner_quotes(image, result):
    """Restore a pair only when a missed line-leading corner and its mate are visible."""
    lines, boxes, words = result.txts, result.boxes, getattr(result, "word_results", None)
    if lines is None or boxes is None or not words or len(lines) != len(words):
        return
    restored = list(lines)
    for i, (text, line, tokens) in enumerate(zip(lines, boxes, words)):
        if text.count("]") != 1 or "[" in text or "「" in text:
            continue
        if "".join(t[0] for t in tokens).replace(" ", "") != text.replace(" ", ""):
            continue
        if (
            not tokens
            or tokens[0][2] is None
            or max(p[1] for p in line[:2]) - min(p[1] for p in line[:2]) > 2
        ):
            continue
        close = next((box for token, _, box in tokens if token == "]"), None)
        if close is None:
            continue
        x0, y0 = min(p[0] for p in line), min(p[1] for p in line)
        x1, y1 = min(p[0] for p in tokens[0][2]), max(p[1] for p in line)
        if not 2 <= x1 - x0 <= (y1 - y0) * 0.7:
            continue
        margin = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        if _corner_glyph(image, margin, True) and _corner_glyph(image, close, False):
            prefix = len(text) - len(text.lstrip())
            restored[i] = text[:prefix] + "「" + text[prefix:].replace("]", "」", 1)
    result.txts = tuple(restored)
