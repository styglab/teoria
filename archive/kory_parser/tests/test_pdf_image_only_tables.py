"""Source-authored ruled tables whose visible cell values are raster images."""

import base64
import io

import pymupdf
import pytest
from PIL import Image

from kory_parser import ParseOptions, parse
from kory_parser.compare import tables_in_order


def raster_table(*, title=True, crossing=False, rotation=0, image=True):
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    if title:
        page.insert_text((30, 30), "Raster values")
    # Three rows, three columns; the first row's last two cells are merged.
    for y in (60, 100, 140, 180):
        page.draw_line((30, y), (270, y))
    for x, top in ((30, 60), (110, 60), (190, 100), (270, 60)):
        page.draw_line((x, top), (x, 180))
    stream = io.BytesIO()
    Image.new("RGB", (20, 8), "blue").save(stream, format="PNG")
    boxes = [
        (40, 70, 80, 86),
        (120, 70, 160, 86),
        (40, 110, 80, 126),
        (120, 110, 160, 126),
        (200, 110, 240, 126),
        (40, 150, 80, 166),
        (120, 150, 160, 166),
        (200, 150, 240, 166),
    ]
    if crossing:
        boxes = [(90, 110, 130, 126)]
    if image:
        for box in boxes:
            page.insert_image(box, stream=stream.getvalue())
        if not crossing:
            page.insert_image((40, 220, 80, 236), stream=stream.getvalue())
    page.set_rotation(rotation)
    data = document.tobytes()
    document.close()
    return data


def all_images(blocks):
    for block in blocks:
        if block.type == "image":
            yield block
        if block.table:
            for row in block.table.cells:
                for cell in row:
                    if not cell.covered:
                        yield from all_images(cell.blocks)
        yield from all_images(block.children)


@pytest.mark.parametrize("images", [False, True])
def test_image_values_keep_the_grid_merges_and_cell_sources(images):
    result = parse(raster_table(), ParseOptions(images=images))
    assert result.success
    tables = [b for b in result.blocks if b.table]
    assert len(tables) == 1
    table = tables[0].table
    assert (table.rows, table.cols, table.geometry_source) == (3, 3, "line")
    assert table.cells[0][1].col_span == 2
    assert table.cells[0][2].covered
    assert tables[0].source.bbox == (30, 60, 270, 180)
    assert all(not cell.text for row in table.cells for cell in row)
    for row in table.cells:
        for cell in row:
            if cell.covered:
                continue
            assert len(cell.blocks) == 1
            block = cell.blocks[0]
            assert block.type == "image"
            assert block.source.page == cell.source.page == 1
            x0, y0, x1, y1 = cell.source.bbox
            left, top, right, bottom = block.source.bbox
            assert x0 <= left < right <= x1
            assert y0 <= top < bottom <= y1
    found = list(all_images(result.blocks))
    assert len(found) == 9
    assert len({b.source.anchor for b in found}) == 9
    assert len([b for b in result.blocks if b.type == "image"]) == 1
    assert len([w for w in result.warnings if w.code == "UNEXTRACTED_IMAGE_TEXT"]) == 9
    assert "Raster values" in result.markdown
    for block in found:
        if images:
            assert block.mime_type == "image/png"
            with Image.open(io.BytesIO(base64.b64decode(block.image_data))) as value:
                assert value.size == (20, 8)
        else:
            assert block.image_data is None


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_image_only_page_keeps_structure_and_needs_ocr(rotation):
    result = parse(raster_table(title=False, rotation=rotation))
    assert not result.success
    assert result.error_code == "NEEDS_OCR"
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(3, 3)]
    assert len(list(all_images(result.blocks))) == 9
    assert len([b for b in result.blocks if b.type == "image"]) == 1


@pytest.mark.parametrize("image,crossing", [(False, False), (True, True)])
def test_blank_grid_or_image_crossing_cells_is_not_a_cell_value(image, crossing):
    result = parse(raster_table(image=image, crossing=crossing))
    assert result.success
    assert not tables_in_order(result.to_dict()["blocks"])
    assert len(list(all_images(result.blocks))) == int(image)


def test_nested_image_table_owns_each_image_once_in_the_smallest_cell():
    document = pymupdf.open()
    page = document.new_page(width=300, height=300)
    page.insert_text((20, 30), "Nested raster values")
    page.draw_rect((20, 50, 280, 240))
    page.draw_line((20, 100), (280, 100))
    for y in (130, 170, 210):
        page.draw_line((50, y), (250, y))
    for x in (50, 150, 250):
        page.draw_line((x, 130), (x, 210))
    stream = io.BytesIO()
    Image.new("RGB", (20, 8), "blue").save(stream, format="PNG")
    for box in [
        (35, 70, 75, 86),
        (60, 140, 100, 156),
        (160, 140, 200, 156),
        (60, 180, 100, 196),
        (160, 180, 200, 196),
    ]:
        page.insert_image(box, stream=stream.getvalue())
    data = document.tobytes()
    document.close()
    result = parse(data)
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 1), (2, 2)]
    outer = next(b.table for b in result.blocks if b.table)
    assert [b.type for b in outer.cells[0][0].blocks] == ["image"]
    assert [b.type for b in outer.cells[1][0].blocks] == ["table"]
    inner = outer.cells[1][0].blocks[0].table
    assert all([b.type for b in cell.blocks] == ["image"] for row in inner.cells for cell in row)
    images = list(all_images(result.blocks))
    assert len(images) == len({b.source.anchor for b in images}) == 5
    assert not any(b.type == "image" for b in result.blocks)
