"""Subprocess contract tests, not real-model/OCR accuracy measurements."""
import json
import sys
from copy import deepcopy

import pytest

from teoria.features.specification_processing.parsing import table_recovery as recovery


def native():
    return {'blocks':[{'type':'paragraph','text':'원문 유지'}],
            'warnings':[{'code':'INVALID_TABLE','source':{'page':2,'bbox':[10,20,300,400]}}]}


async def test_absent_supply_list_does_not_trigger_an_ocr_attempt(tmp_path):
    result=await recovery.recover_table_regions(tmp_path/'plain.pdf',{'warnings':[]},tmp_path/'native.json','missing-python')
    assert result['status']=='not_needed'


@pytest.mark.parametrize('suffix',['.hwp','.hwpx','.docx'])
async def test_unrenderable_formats_are_reported_without_claiming_recovery(tmp_path,suffix):
    result=await recovery.recover_table_regions(tmp_path/('file'+suffix),native(),tmp_path/'native.json','missing-python')
    assert result['status']=='unsupported'


async def test_targeted_ocr_keeps_original_and_adds_source_located_supplementary_text(tmp_path,monkeypatch):
    code='''import sys,json
from pathlib import Path
regions=json.loads(sys.argv[3]);assert regions==[{'page':2,'bbox':[10,20,300,400]}]
Path(sys.argv[2]).write_text(json.dumps([{'region':regions[0],'blocks':[{'type':'paragraph','text':'장치 2 대','source':{'page':2,'bbox':[10,20,150,40],'anchor':'ocr:table_recovery'}}]}]))
'''
    monkeypatch.setattr(recovery,'RECOVERY_CODE',code)
    data=native();result=await recovery.recover_table_regions(tmp_path/'file.pdf',data,tmp_path/'native.json',sys.executable)
    assert result['status']=='text_recovered'
    assert data['blocks'][0]['text']=='원문 유지'
    assert data['blocks'][1]['text']=='장치 2 대'
    assert data['blocks'][1]['source']['page']==2
    assert not (tmp_path/'table_ocr_recovery.json').exists()


async def test_failure_keeps_native_evidence_and_does_not_expose_subprocess_text(tmp_path,monkeypatch):
    monkeypatch.setattr(recovery,'RECOVERY_CODE',"raise RuntimeError('PRIVATE_SOURCE')")
    data=native();before=deepcopy(data)
    result=await recovery.recover_table_regions(tmp_path/'file.pdf',data,tmp_path/'native.json',sys.executable)
    assert result['status']=='failed' and result['reason']=='ocr_process_failed'
    assert data==before and 'PRIVATE_SOURCE' not in str(result)


async def test_recovery_is_bounded_and_partial_is_not_complete(tmp_path,monkeypatch):
    data=native();data['warnings']*=4
    for i,w in enumerate(data['warnings']):
        data['warnings'][i]={'code':'INVALID_TABLE','source':{'page':i+1,'bbox':[10,20,300,400]}}
    monkeypatch.setattr(recovery,'RECOVERY_CODE',"import json,sys;from pathlib import Path; r=json.loads(sys.argv[3]);assert len(r)==3;Path(sys.argv[2]).write_text(json.dumps([{'region':v,'blocks':[]} for v in r]))")
    result=await recovery.recover_table_regions(tmp_path/'file.pdf',data,tmp_path/'native.json',sys.executable)
    assert len(result['attempted_regions'])==3 and result['status']=='partial'
