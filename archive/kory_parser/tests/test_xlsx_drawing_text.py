"""Shape labels are independent worksheet content, including grouped shapes."""

import pytest

from kory_parser import ParseOptions, parse
from kory_parser.models import plain_text

from .document_fixtures import zip_document

SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
TEXT = "http://schemas.openxmlformats.org/drawingml/2006/main"


def workbook(shapes, *, anchor="twoCellAnchor", cells=True, external=False):
    return zip_document(
        {
            "xl/workbook.xml": f'<workbook xmlns="{SHEET}" xmlns:r="{REL}">'
            '<sheets><sheet name="Specification" sheetId="1" r:id="s"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="s" '
            'Target="worksheets/specification.xml"/></Relationships>',
            "xl/worksheets/specification.xml": f'<worksheet xmlns="{SHEET}" xmlns:r="{REL}">'
            "<sheetData>"
            + ('<row r="1"><c r="A1" t="inlineStr"><is><t>Cabinet</t></is></c></row>' if cells else "")
            + '</sheetData><drawing r:id="d"/></worksheet>',
            "xl/worksheets/_rels/specification.xml.rels": '<Relationships><Relationship Id="d" '
            + (
                'TargetMode="External" Target="https://example.invalid/drawing.xml"'
                if external
                else 'Target="../drawings/labels.xml"'
            )
            + "/></Relationships>",
            "xl/drawings/labels.xml": f'<xdr:wsDr xmlns:xdr="{DRAWING}" xmlns:a="{TEXT}">'
            f"<xdr:{anchor}>{shapes}</xdr:{anchor}></xdr:wsDr>",
            # Unreferenced drawings must never leak into the selected sheet.
            "xl/drawings/unused.xml": f'<xdr:wsDr xmlns:xdr="{DRAWING}" xmlns:a="{TEXT}">'
            "<xdr:twoCellAnchor>" + shape("Unused", identifier=9) + "</xdr:twoCellAnchor></xdr:wsDr>",
        }
    )


def shape(text, *, identifier=7, hidden=False):
    return (
        "<xdr:sp><xdr:nvSpPr><xdr:cNvPr "
        f'id="{identifier}" hidden="{int(hidden)}"/></xdr:nvSpPr>'
        "<xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>"
        + text
        + "</a:t></a:r></a:p></xdr:txBody></xdr:sp>"
    )


@pytest.mark.parametrize("anchor", ["oneCellAnchor", "twoCellAnchor", "absoluteAnchor"])
def test_worksheet_shape_text_is_extracted_without_ocr_or_images(anchor):
    result = parse(workbook(shape("Walnut finish"), anchor=anchor), ParseOptions(images=False, ocr=False))
    assert result.success
    assert [b.type for b in result.blocks] == ["heading", "table", "paragraph"]
    assert result.blocks[1].table.cells[0][0].text == "Cabinet"
    block = result.blocks[2]
    assert block.text == "Walnut finish"
    assert block.source.part == "xl/drawings/labels.xml"
    assert block.source.anchor == "shape:7"
    assert "Unused" not in plain_text(result.blocks)


def test_grouped_shapes_retain_runs_line_breaks_and_paragraph_order():
    label = shape("Oak</a:t></a:r><a:br/><a:r><a:t>edge")
    label = label.replace(
        "</a:p></xdr:txBody>", "</a:p><a:p><a:fld><a:t>2 mm</a:t></a:fld></a:p></xdr:txBody>"
    )
    result = parse(workbook("<xdr:grpSp><xdr:grpSp>" + label + "</xdr:grpSp></xdr:grpSp>"))
    assert result.success
    assert result.blocks[-1].text == "Oak\nedge\n2 mm"


def test_shape_only_sheet_retains_heading_and_text():
    result = parse(workbook(shape("Handling instructions"), cells=False))
    assert result.success
    assert [b.type for b in result.blocks] == ["heading", "paragraph"]
    assert result.blocks[-1].text == "Handling instructions"


def test_hidden_shapes_and_groups_do_not_add_text():
    hidden_group = '<xdr:grpSp><xdr:nvGrpSpPr><xdr:cNvPr hidden="true"/></xdr:nvGrpSpPr>'
    hidden_group += shape("Hidden group") + "</xdr:grpSp>"
    result = parse(workbook(shape("Hidden label", hidden=True) + hidden_group + shape("Visible label")))
    assert result.success
    assert plain_text(result.blocks) == "Specification\nCabinet\nVisible label"


def test_external_drawing_is_not_fetched():
    result = parse(workbook(shape("External"), external=True))
    assert result.success
    assert plain_text(result.blocks) == "Specification\nCabinet"


def test_page_selection_skips_drawing_content():
    result = parse(workbook(shape("Skipped")), ParseOptions(pages=(2,)))
    assert result.success
    assert not result.blocks


def test_shape_groups_respect_nesting_budget():
    grouped = "<xdr:grpSp>" * 3 + shape("Nested") + "</xdr:grpSp>" * 3
    result = parse(workbook(grouped), ParseOptions(max_depth=2))
    assert not result.success
    assert result.error_code == "RESOURCE_LIMIT"
