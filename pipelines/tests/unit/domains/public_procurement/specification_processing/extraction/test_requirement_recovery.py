import hashlib
import json
from pathlib import Path
import pytest
from teoria_pipelines.domains.public_procurement.specification_processing.extraction.requirement_extraction import extract_requirements

@pytest.fixture
def saved_parse(tmp_path):
    source=tmp_path/'source.hwp';source.write_bytes(b'parser source fixture')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    native=tmp_path/'native.json';native.write_text(json.dumps({'sha256':digest}))
    document={'document_id':'doc','source_path':str(source),'source_sha256':digest,'parse_path':str(native),
        'native_sha256':hashlib.sha256(native.read_bytes()).hexdigest(),'nodes':[{'node_id':'n','kind':'cell','text':'CPU 16core 이상','native_ref':'/blocks/0'}]}
    graph={'document_id':'doc','entities':[{'id':'cpu','name':'CPU','kind':'equipment'}],'relations':[],
        'requirements':[],'declared_quantities':[]}
    folder=tmp_path/'input';folder.mkdir()
    (folder/'document.json').write_text(json.dumps(document));(folder/'graph.json').write_text(json.dumps(graph))
    return folder

async def test_inventory_omitted_cell_is_recovered_once_with_literal_validation(saved_parse,tmp_path):
    class Backend:
        def __init__(self):self.attempts=[]
        async def generate(self,prompt,request,out):
            self.attempts.append(request['attempt'])
            if request['attempt']=='initial':return {'facts':[],'unresolved':[]}
            fragment=request['fragments'][0][0]
            return {'facts':[[fragment,['cpu'],'core_count','CPU','number','gte','이상','16','core',[]]],'unresolved':[]}
    backend=Backend()
    summary=await extract_requirements('doc',saved_parse,tmp_path/'output',backend,None)
    assert backend.attempts==['initial','missing_fragment_recovery']
    assert summary['recovery_passes']==1 and summary['uncovered_spec_fragments']==0
    assert summary['input_coverage']['missing_node_ids']==[]
    attrs=json.loads((tmp_path/'output/attribute_graph.json').read_text())['attributes']
    assert attrs[0]['value_raw']=='16' and attrs[0]['unit_raw']=='core'

async def test_unsolved_missing_requirement_is_partial_without_an_approval_gate(saved_parse,tmp_path):
    class Empty:
        def __init__(self):self.calls=0
        async def generate(self,*args):self.calls+=1;return {'facts':[],'unresolved':[]}
    backend=Empty();summary=await extract_requirements('doc',saved_parse,tmp_path/'output',backend,None)
    assert backend.calls==2
    assert summary['status']=='partial' and summary['zero_detail_attributes']
    assert summary['uncovered_spec_fragments']==1

async def test_non_server_pressure_cell_is_recovered_with_original_subject_and_unit(saved_parse,tmp_path):
    document=json.loads((saved_parse/'document.json').read_text())
    document['nodes'][0]['text']='압력 펌프 40MPa 이상'
    (saved_parse/'document.json').write_text(json.dumps(document))
    graph=json.loads((saved_parse/'graph.json').read_text())
    graph['entities']=[{'id':'pump','name':'압력 펌프','kind':'equipment'}]
    (saved_parse/'graph.json').write_text(json.dumps(graph))
    class Backend:
        def __init__(self):self.calls=[]
        async def generate(self,prompt,request,out):
            self.calls.append(request['attempt'])
            if request['attempt']=='initial':return {'facts':[],'unresolved':[]}
            fragment=request['fragments'][0][0]
            return {'facts':[[fragment,['pump'],'operating_pressure',None,'number','gte','이상','40','MPa',[]]],'unresolved':[]}
    backend=Backend();summary=await extract_requirements('doc',saved_parse,tmp_path/'output',backend,None)
    assert backend.calls==['initial','missing_fragment_recovery']
    assert summary['uncovered_spec_fragments']==0
    attribute=json.loads((tmp_path/'output/attribute_graph.json').read_text())['attributes'][0]
    assert attribute['subject_ids']==['pump'] and attribute['property_key']=='operating_pressure'
    assert attribute['value_raw']=='40' and attribute['unit_raw']=='MPa'
