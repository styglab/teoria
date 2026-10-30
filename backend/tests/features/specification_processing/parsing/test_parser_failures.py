"""Parser process diagnostics preserve safe types, not raw stderr/source content."""
import sys
import pytest
from teoria.features.specification_processing.parsing import document_parser
from teoria.features.specification_processing.processing_errors import SpecificationProcessingError


async def test_scan_only_pdf_reports_ocr_requirement(tmp_path,monkeypatch):
    source=tmp_path/'scan.pdf';source.write_bytes(b'fixture')
    monkeypatch.setattr(document_parser,'PARSER_CODE',"import json,sys; from pathlib import Path; Path(sys.argv[2]).write_text(json.dumps({'success':False,'warnings':[{'code':'NEEDS_OCR'}]}))")
    with pytest.raises(SpecificationProcessingError) as caught:
        await document_parser.parse_document(source,tmp_path/'native.json','scan',sys.executable)
    assert caught.value.code=='needs_ocr'
    assert caught.value.details=={'warning_codes':['NEEDS_OCR']}


async def test_subprocess_exception_type_is_retained_but_error_body_is_not(tmp_path,monkeypatch):
    source=tmp_path/'broken.pdf';source.write_bytes(b'fixture')
    monkeypatch.setattr(document_parser,'PARSER_CODE',"raise RuntimeError('PRIVATE_SOURCE_BODY')")
    with pytest.raises(SpecificationProcessingError) as caught:
        await document_parser.parse_document(source,tmp_path/'native.json','broken',sys.executable)
    assert caught.value.code=='parser_process_failed'
    assert caught.value.details['exception_type']=='RuntimeError'
    assert 'PRIVATE_SOURCE_BODY' not in str(caught.value)
