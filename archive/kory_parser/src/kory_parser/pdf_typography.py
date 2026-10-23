"""Recover PDF heading structure from measured typography and page context."""

import re
from collections import Counter
from dataclasses import dataclass
from statistics import median


def bold_font(char):
    if char.get("font_flags", 0) & 16:
        return True
    name = char.get("fontname", "")
    try:
        name = name.encode("latin1").decode("cp949")
    except (UnicodeError, LookupError):
        pass
    return bool(re.search(r"bold|black|heavy|demi|헤드라인|견고딕|견명조", name, re.IGNORECASE))


@dataclass(frozen=True)
class LineStyle:
    size: float
    bold_fraction: float
    native_block: int | None = None
    font: str = ""
    color: int = 0
    horizontal: bool = True


class PdfTypography:
    """Keep compact measurements, releasing page glyph arrays after extraction."""

    def __init__(self, *, extract_contents=False):
        self.styles = {}
        self.pages = {}
        self.sizes = Counter()
        self.fonts = {}
        self.body_fonts = Counter()
        self.colors = Counter()
        self.contents_page_labels = set()
        self.extract_contents = extract_contents

    def page(self, number, chars, height):
        sizes = Counter(round(c["size"], 1) for c in chars if c["text"].strip())
        self.pages[number] = (sizes.most_common(1)[0][0] if sizes else 0, height)
        self.sizes.update(sizes)
        self.body_fonts.update(c.get("fontname", "") for c in chars if c["text"].strip())
        self.colors.update(c.get("font_color", 0) for c in chars if c["text"].strip())

    def line(self, block, chars):
        self.region(block.source, block.text, chars)

    def region(self, source, text, chars):
        glyphs = [c for c in chars if c["text"].strip()]
        if glyphs:
            for char in glyphs:
                key = (char.get("fontname", ""), char.get("font_flags", 0))
                if key not in self.fonts:
                    self.fonts[key] = bold_font(char)
            self.styles[(source.page, source.bbox, text)] = LineStyle(
                median(c["size"] for c in glyphs),
                sum(self.fonts[(c.get("fontname", ""), c.get("font_flags", 0))] for c in glyphs)
                / len(glyphs),
                Counter(c.get("native_block") for c in glyphs).most_common(1)[0][0],
                Counter(c.get("fontname", "") for c in glyphs).most_common(1)[0][0],
                Counter(c.get("font_color", 0) for c in glyphs).most_common(1)[0][0],
                sum(c.get("upright", True) for c in glyphs) / len(glyphs) > 0.8,
            )

    def headings(self, blocks):
        if not self.sizes:
            return
        body_size = self.sizes.most_common(1)[0][0]
        body_color = self.colors.most_common(1)[0][0]
        body_font = self.body_fonts.most_common(1)[0][0]
        repeated = Counter()
        for block in blocks:
            if self.running_margin(block):
                repeated[block.text.strip()] += 1
        for block in blocks:
            if block.type != "paragraph" or not block.source:
                continue
            style = self.styles.get((block.source.page, block.source.bbox, block.text))
            if not style or not style.horizontal:
                continue
            text = block.text.strip()
            if not text or len(text) > 100 or re.search(r"[.!。]$", text):
                continue
            if re.fullmatch(r"[\s\d.\-/–—년월일]+", text):
                continue
            if re.match(r"^\d+(?:\s+\d+){2,}\b", text):
                continue
            if re.match(r"\d+(?:\.\d+)?\s*(?:[KMGT]B|[GM]Hz|[kK]?W|V|A|%)\b", text):
                continue
            if self.running_margin(block) and repeated[text] >= 2:
                continue
            page_size, _ = self.pages[block.source.page]
            large = style.size >= page_size * 1.35 or style.size >= body_size * 1.65
            section = bool(re.match(r"(?:\d{1,2}(?:\.\d+)*[.) ]|[Ⅰ-ⅫIVX]+[. ]|[가-힣][.)])\s*\S", text))
            if (
                not section
                and re.match(r"[^:：]{1,20}[:：]\s*\S", text)
                and (
                    style.bold_fraction < 0.6
                    or style.size < page_size * 1.12
                    or re.match(r"[^:：]+[:：]\s*[\d±=]", text)
                )
            ):
                continue
            distinctive = style.size >= page_size * 1.12 and (section or style.bold_fraction >= 0.6)
            numbered_bold = section and style.bold_fraction >= 0.7 and len(text) <= 70
            colored_style = (
                style.color != body_color
                and style.font != body_font
                and style.size >= page_size
                and not re.match(r"(?:fig(?:ure)?\.?|table|그림|표)\s*\d", text, re.IGNORECASE)
            )
            if large or distinctive or numbered_bold or colored_style:
                block.type = "heading"
                block.level = 1 if large else 2
        self.heading_levels(blocks, body_size)

    def style(self, block):
        if not block.source:
            return None
        return self.styles.get((block.source.page, block.source.bbox, block.text))

    def heading_levels(self, blocks, body_size):
        headings = [b for b in blocks if b.type == "heading" and self.style(b)]
        body_color = self.colors.most_common(1)[0][0]
        colored_sizes = {}
        for block in headings:
            style = self.style(block)
            if style.color != body_color:
                key = (style.font, style.color)
                colored_sizes[key] = max(colored_sizes.get(key, 0), style.size)

        def measured_size(block):
            style = self.style(block)
            anchor = colored_sizes.get((style.font, style.color), style.size)
            return anchor if style.size >= anchor * 0.8 else style.size

        sizes = []
        for size in sorted({measured_size(b) for b in headings}, reverse=True):
            if not sizes or size < sizes[-1] * 0.95:
                sizes.append(size)
        title = any(
            not re.match(r"\d+[.) ]", b.text)
            and self.style(b).size >= body_size * 1.25
            and b.source.page == min(self.pages)
            and b.source.bbox[1] < self.pages[b.source.page][1] * 0.2
            for b in headings
        )
        for block in headings:
            number = re.match(r"^(\d+(?:\.\d+)*)(?:[.)]\s*|\s+)(?=\S)", block.text)
            if number:
                block.level = min(6, number[1].count(".") + 1 + int(title))
            else:
                size = measured_size(block)
                block.level = min(
                    6, next((i + 1 for i, anchor in enumerate(sizes) if size >= anchor * 0.95), len(sizes))
                )

    def running_margin(self, block):
        if not block.source or not block.source.bbox or block.source.page not in self.pages:
            return False
        _, height = self.pages[block.source.page]
        return block.source.bbox[3] < height * 0.07 or block.source.bbox[1] > height * 0.93
