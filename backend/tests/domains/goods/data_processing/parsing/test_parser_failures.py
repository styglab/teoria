"""Parser process diagnostics preserve safe types, not raw stderr/source content."""
import sys
import pytest
from teoria.domains.goods.data_processing.parsing import document_parser
from teoria.domains.goods.data_processing.errors import SpecificationProcessingError


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


@pytest.mark.parametrize('anchor',['ocr:confidence=0.98',None])
async def test_pipeline_enables_ocr_and_reports_its_actual_use(tmp_path,monkeypatch,anchor):
    # A parser double verifies the subprocess contract; real OCR is tested separately on the scanned sample.
    fake=tmp_path/'kory_parser.py'
    fake.write_text('''import hashlib
class ParseOptions:
 def __init__(self,**kw):
  assert kw['ocr'] is True and kw['extract_contents'] is True
class Result:
 def __init__(self,p):self.p=p
 def to_dict(self):
  return {'success':True,'sha256':hashlib.sha256(self.p.read_bytes()).hexdigest(),
   'parser_version':'test','blocks':[{'type':'paragraph','text':'Digital Ultrasound Imaging System',
    'source':{'page':1,'anchor':'ocr:confidence=0.98','bbox':[0,0,100,20]}}]}
def parse(path,options):return Result(path)
'''.replace("'ocr:confidence=0.98'",repr(anchor)))
    monkeypatch.setenv('PYTHONPATH',str(tmp_path))
    source=tmp_path/'scan.pdf';source.write_bytes(b'fixture')
    result=await document_parser.parse_document(source,tmp_path/'native.json','scan',sys.executable)
    assert result['ocr_enabled'] is True and result['ocr'] is bool(anchor)
    assert result['ocr_pages']==([1] if anchor else [])
    assert result['nodes'][0]['source']['bbox']==[0,0,100,20]
