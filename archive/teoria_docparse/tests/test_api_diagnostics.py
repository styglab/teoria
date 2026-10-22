"""Reader dispatch and diagnostics must distinguish bad inputs from parser defects."""

import os
import subprocess
import sys

import pytest

from teoria_docparse import parse

from .document_fixtures import docx, zip_document


@pytest.mark.parametrize("error", [KeyError("internal lookup"), IndexError("internal index")])
def test_parser_defects_are_not_reported_as_invalid_documents(monkeypatch, error):
    from teoria_docparse import office

    def broken(data, options):
        raise error

    monkeypatch.setattr(office, "parse_docx", broken)
    result = parse(docx("<w:p/>"))
    assert not result.success
    assert result.error_code == "INTERNAL_ERROR"
    assert result.warnings[0].code == "INTERNAL_ERROR"
    assert type(error).__name__ in result.warnings[0].message


def test_missing_referenced_package_member_is_an_invalid_file():
    data = zip_document(
        {
            "ppt/presentation.xml": '<presentation xmlns:r="rels"><sldIdLst><sldId r:id="missing"/></sldIdLst></presentation>',
            "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="missing" Target="slides/absent.xml"/></Relationships>',
        }
    )
    result = parse(data)
    assert result.error_code == "INVALID_FILE"
    assert "Missing ZIP member" in result.warnings[0].message


def test_cold_hwpx_parse_does_not_load_unrelated_readers(tmp_path):
    from .document_fixtures import hwpx

    path = tmp_path / "sample.hwpx"
    path.write_bytes(hwpx("<p><run><t>CPU</t></run></p>"))
    code = """import sys
from teoria_docparse import parse
assert parse(sys.argv[1]).success
assert 'teoria_docparse.hangul_xml' in sys.modules
for module in ('office', 'hwp_binary', 'hwp_legacy', 'pdf', 'ocr'):
    assert 'teoria_docparse.' + module not in sys.modules, module
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True, env=os.environ.copy())


@pytest.mark.parametrize("string_index", [-1, 99])
def test_invalid_workbook_string_indices_are_input_errors(string_index):
    data = zip_document(
        {
            "xl/workbook.xml": '<workbook xmlns:r="rels"><sheets><sheet name="Sheet" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/sharedStrings.xml": "<sst><si><t>CPU</t></si></sst>",
            "xl/worksheets/sheet1.xml": f'<worksheet><sheetData><row><c r="A1" t="s"><v>{string_index}</v></c></row></sheetData></worksheet>',
        }
    )
    result = parse(data)
    assert result.error_code == "INVALID_FILE"
    assert "shared string index" in result.warnings[0].message
