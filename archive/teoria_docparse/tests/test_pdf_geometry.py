"""Original small PDF documents exercise clipping, dotted rules and nested structure."""

from teoria_docparse import parse
from teoria_docparse.compare import block_text, normalized_text, tables_in_order


def pdf(stream: bytes, width=300, height=300) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 4 0 R /F2 6 0 R >> >> /Contents 5 0 R >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def clipped_text(x, y, w, h, text):
    return f"q {x} {y} {w} {h} re W n BT /F1 10 Tf {x + 5} {y + h / 2} Td ({text}) Tj ET Q\n".encode()


def ruled_grid(dotted=False):
    stream = b""
    if dotted:
        for y in (100, 150, 200):
            for x in range(40, 240, 2):
                stream += f"{x} {y} m {x + 0.5} {y} l S\n".encode()
        for x in (40, 140, 240):
            for y in range(100, 200, 2):
                stream += f"{x} {y} m {x} {y + 0.5} l S\n".encode()
    else:
        for y in (100, 150, 200):
            stream += f"40 {y} m 240 {y} l S\n".encode()
        for x in (40, 140, 240):
            stream += f"{x} 100 m {x} 200 l S\n".encode()
    return stream


def test_short_dotted_cell_borders_are_continuous_table_evidence():
    stream = ruled_grid(dotted=True)
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += clipped_text(x, y, 100, 50, value)
    result = parse(pdf(stream))
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert len(tables) == 1
    assert (tables[0]["rows"], tables[0]["cols"]) == (2, 2)
    assert [c["text"] for row in tables[0]["cells"] for c in row] == ["CPU", "32", "RAM", "64"]


def test_grid_gap_keeps_text_when_one_cell_has_no_clip_path():
    stream = ruled_grid()
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM")]:
        stream += clipped_text(x, y, 100, 50, value)
    stream += b"BT /F1 10 Tf 145 125 Td (64) Tj ET\n"
    result = parse(pdf(stream))
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert table.cells[1][1].text == "64"
    assert table.cells[1][1].source.anchor.startswith("grid_fill:")


def test_nested_table_does_not_duplicate_or_drop_surrounding_text():
    stream = b"40 50 180 180 re S 40 200 m 220 200 l S\n"
    stream += clipped_text(40, 200, 180, 30, "Heading")
    stream += b"q 40 50 180 150 re W n\nBT /F1 10 Tf 50 180 Td (Before) Tj ET\n"
    for y in (80, 120, 160):
        stream += f"60 {y} m 200 {y} l S\n".encode()
    for x in (60, 130, 200):
        stream += f"{x} 80 m {x} 160 l S\n".encode()
    for x, y, value in [(60, 120, "CPU"), (130, 120, "32"), (60, 80, "RAM"), (130, 80, "64")]:
        stream += clipped_text(x, y, 70, 40, value)
    stream += b"BT /F1 10 Tf 50 60 Td (After) Tj ET Q\n"
    result = parse(pdf(stream))
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 1), (2, 2)]
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "HeadingBeforeCPU32RAM64After"
    cell = result.blocks[0].table.cells[1][0]
    assert [b.type for b in cell.blocks] == ["paragraph", "table", "paragraph"]
    assert "/" not in cell.text


def test_repeated_nearly_equal_clip_rectangles_are_one_cell():
    stream = ruled_grid()
    for x, y, value in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += clipped_text(x, y, 100, 50, value)
        stream += f"q {x + 0.1} {y + 0.1} 99.8 49.8 re W n Q\n".encode()
    result = parse(pdf(stream))
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 2)]


def test_white_and_filled_background_rectangles_do_not_create_fake_tables():
    stream = b"1 1 1 RG 40 100 100 100 re S 140 100 100 100 re S 0 0 0 rg\n"
    stream += b"BT /F1 12 Tf 50 150 Td (Plain paragraph) Tj ET\n"
    result = parse(pdf(stream))
    assert result.success
    assert not tables_in_order(result.to_dict()["blocks"])
    assert "Plain paragraph" in result.markdown


def test_shaded_cells_form_a_table_without_stroked_borders():
    stream = b""
    for x, y, text in [(40, 150, "CPU"), (140, 150, "32"), (40, 100, "RAM"), (140, 100, "64")]:
        stream += f"0.9 0.8 0.5 rg {x} {y} 100 50 re f 0 0 0 rg BT /F1 10 Tf {x + 5} {y + 25} Td ({text}) Tj ET\n".encode()
    result = parse(pdf(stream))
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert (table.rows, table.cols) == (2, 2)
    assert table.geometry_source == "fill"
    assert [c.text for row in table.cells for c in row] == ["CPU", "32", "RAM", "64"]


def test_repeated_shaded_values_keep_their_aligned_unshaded_labels():
    stream = b""
    for y, label, value in [(200, "CPU", "32"), (150, "RAM", "64"), (100, "DISK", "128")]:
        stream += f"0.9 0.8 0.5 rg 140 {y} 100 50 re f 0 0 0 rg BT /F1 10 Tf 40 {y + 25} Td ({label}) Tj ET BT /F1 10 Tf 145 {y + 25} Td ({value}) Tj ET\n".encode()
    result = parse(pdf(stream))
    assert result.success
    table = next(b.table for b in result.blocks if b.table)
    assert (table.rows, table.cols) == (3, 2)
    assert [c.text for row in table.cells for c in row] == ["CPU", "32", "RAM", "64", "DISK", "128"]


def test_inline_font_change_does_not_move_punctuation_to_the_word_end():
    stream = b"BT /F1 10 Tf 40 150 Td (A) Tj ET BT /F1 10 Tf 48 150 Td (B) Tj ET BT /F2 10 Tf 47 150 Td (.) Tj ET\n"
    result = parse(pdf(stream))
    assert result.success
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "A.B"


def test_circle_composition_requires_geometric_overlap():
    from teoria_docparse.pdf import normalize_glyphs

    def char(text, x0, x1, top, bottom, size):
        return {
            "text": text,
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "doctop": top,
            "size": size,
            "upright": True,
            "fontname": text,
        }

    circle = char("◯", 0, 12, 0, 12, 12)
    digit = char("2", 3, 8, 2, 10, 8)
    restored, count = normalize_glyphs([circle, digit])
    assert count == 1
    assert [c["text"] for c in restored] == ["②"]
    adjacent = char("2", 14, 20, 2, 10, 8)
    unchanged, count = normalize_glyphs([circle, adjacent])
    assert count == 0
    assert [c["text"] for c in unchanged] == ["◯", "2"]


def test_toc_dot_leaders_do_not_change_the_page_reference():
    stream = b"BT /F1 12 Tf 40 150 Td (Chapter 1..........3) Tj ET\n"
    result = parse(pdf(stream))
    assert result.success
    assert normalized_text(block_text(result.to_dict()["blocks"])) == "Chapter13"
