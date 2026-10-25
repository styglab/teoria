"""MuPDF document boundary and measured page primitives. No alternate PDF engine."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property

from .models import ParseError
from .pdf_fonts import glyph_replacements


@contextmanager
def native_document(data):
    try:
        import pymupdf
    except ImportError as error:
        raise ParseError("DEPENDENCY_MISSING", "Install the required pymupdf dependency") from error
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as error:
        raise ParseError("INVALID_FILE", "MuPDF rejected the input") from error
    try:
        if document.needs_pass:
            raise ParseError("ENCRYPTED", "PDF requires a password")
        yield document
    finally:
        document.close()


def document_metadata(document):
    """Preserve PDF Info names rather than exposing engine-specific properties."""
    kind, reference = document.xref_get_key(-1, "Info")
    if kind != "xref":
        return {}
    xref = int(reference.split()[0])
    values = {}
    for name in document.xref_get_keys(xref):
        kind, value = document.xref_get_key(xref, name)
        if kind == "string":
            values[name] = value
        elif kind == "int":
            values[name] = int(value)
        elif kind == "float":
            values[name] = float(value)
        elif kind == "bool":
            values[name] = value == "true"
    return values


@dataclass
class NativePage:
    page_number: int
    width: float
    height: float
    initial_doctop: float
    objects: dict
    clips: list
    unresolved_glyphs: int = 0

    @property
    def chars(self):
        return self.objects["char"]

    @property
    def rects(self):
        return self.objects["rect"]

    @property
    def images(self):
        return self.objects["image"]

    @cached_property
    def edges(self):
        from .pdf_rules import edges_from_objects

        return edges_from_objects(self.objects)

    def filter(self, predicate):
        return NativePage(
            self.page_number,
            self.width,
            self.height,
            self.initial_doctop,
            {kind: [obj for obj in values if predicate(obj)] for kind, values in self.objects.items()},
            self.clips,
        )


def load_native_page(native, options, initial_doctop=0):
    """Use displayed page coordinates for glyphs, drawings, clips and images alike."""
    import pymupdf

    objects = {"char": [], "line": [], "rect": [], "curve": [], "image": []}
    page = NativePage(native.number + 1, native.rect.width, native.rect.height, initial_doctop, objects, [])
    height = page.height
    page_rotation = native.rotation
    rotation = native.rotation_matrix

    def box(kind, bounds, **extra):
        if page_rotation:
            bounds = pymupdf.Rect(bounds) * rotation
        x0, top, x1, bottom = bounds
        return {
            "object_type": kind,
            "page_number": page.page_number,
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "y0": height - bottom,
            "y1": height - top,
            "width": x1 - x0,
            "height": bottom - top,
            "doctop": page.initial_doctop + top,
            **extra,
        }

    raw = native.get_text("rawdict", flags=0)
    replacements = glyph_replacements(native, raw)
    for block_index, block in enumerate(raw["blocks"]):
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line["spans"]
            # Broken legacy font ascenders can split same-baseline Han/Hangul
            # spans into apparent rows. Source glyph bboxes remain unchanged.
            baseline_aligned = (
                not page_rotation
                and abs(line["dir"][1]) < 0.01
                and max(s["origin"][1] for s in spans) - min(s["origin"][1] for s in spans) <= 0.5
            )
            for span in line["spans"]:
                dx, dy = line["dir"]
                if page_rotation:
                    dx, dy = dx * rotation.a + dy * rotation.c, dx * rotation.b + dy * rotation.d
                direction = (
                    "ltr"
                    if abs(dx) >= abs(dy) and dx >= 0
                    else "rtl"
                    if abs(dx) >= abs(dy)
                    else "ttb"
                    if dy >= 0
                    else "btt"
                )
                for char in span["chars"]:
                    text = replacements.get((span["font"], tuple(char["origin"])), char["c"])
                    page.unresolved_glyphs += text.count("\ufffd")
                    objects["char"].append(
                        box(
                            "char",
                            char["bbox"],
                            text=text,
                            size=span["size"],
                            fontname=span["font"],
                            font_flags=span.get("flags", 0),
                            font_color=span.get("color", 0),
                            native_block=block_index,
                            native_line=(block_index, line_index),
                            upright=abs(dy) < 0.01,
                            **({"layout_top": line["bbox"][1]} if baseline_aligned else {}),
                            **(
                                {"text_direction": direction} if page_rotation or direction != "ltr" else {}
                            ),
                        )
                    )
                    if len(objects["char"]) > options.max_xml_nodes:
                        raise ParseError("RESOURCE_LIMIT", "PDF page complexity exceeds budget")
    clips = []
    drawings = native.get_cdrawings(extended=True)
    if len(drawings) > 100_000:
        raise ParseError("RESOURCE_LIMIT", "PDF page complexity exceeds budget")
    for path in drawings:
        if path["type"] == "group":
            continue
        if path["type"] == "clip":
            for item in path["items"]:
                if item[0] == "re":
                    ax, ay, bx, by = item[1]
                    if page_rotation:
                        ax, ay, bx, by = (
                            pymupdf.Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)) * rotation
                        )
                    x0, top, x1, bottom = min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
                    clips.append((x0, height - bottom, x1, height - top))
            if len(clips) > 4000:
                raise ParseError("RESOURCE_LIMIT", "Too many rectangular clipping paths")
            continue
        stroke = "s" in path["type"] and path.get("stroke_opacity", 1) != 0
        fill = "f" in path["type"] and path.get("fill_opacity", 1) != 0
        style = {
            "stroke": stroke,
            "fill": fill,
            "linewidth": path.get("width") or 0,
            "stroking_color": path.get("color"),
            "non_stroking_color": path.get("fill"),
        }
        # MuPDF reports many rectangular fills as four connected lines.
        vertices = {tuple(p) for item in path["items"] if item[0] == "l" for p in item[1:]}
        rectangular = (
            len(path["items"]) == 4
            and len(vertices) == 4
            and len({p[0] for p in vertices}) == len({p[1] for p in vertices}) == 2
        )
        if rectangular:
            bounds = path["rect"]
            objects["rect"].append(box("rect", bounds, **style))
            continue
        for item in path["items"]:
            if item[0] == "re":
                ax, ay, bx, by = item[1]
                objects["rect"].append(
                    box("rect", (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)), **style)
                )
            elif item[0] == "l":
                a, b = item[1:]
                objects["line"].append(
                    box("line", (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])), **style)
                )
    for index, image in enumerate(native.get_image_info(xrefs=options.images)):
        content = native.parent.extract_image(image["xref"]) if options.images and image.get("xref") else None
        objects["image"].append(
            box(
                "image",
                image["bbox"],
                name=f"image:{index}",
                stream=None,
                image_bytes=content["image"] if content else None,
                image_ext=content["ext"] if content else None,
            )
        )
    page.clips = clips
    return page
