"""Actual Prefect extraction Tasks with controlled parser/model adapters; no quality claim."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from prefect.testing.utilities import prefect_test_harness
from teoria_pipelines.domains.public_procurement.specification_processing import flows,tasks
from teoria_pipelines.domains.public_procurement.specification_processing.parsing import document_parser

pytestmark=pytest.mark.skipif(os.getenv('TEORIA_TEST_SPECIFICATION_EVALUATION')!='1',reason='opt-in isolated Prefect evaluation integration')


@pytest.mark.parametrize('missing_unit_and_duplicate',[False,True])
async def test_real_prefect_runs_shared_extraction_without_operational_db(tmp_path,monkeypatch,missing_unit_and_duplicate):
    source=tmp_path/'specification.hwp';source.write_bytes(b'controlled source fixture')
    async def parse(source,native_path,document_id,parser_python):
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        native_path.write_text(json.dumps({'sha256':digest}))
        nodes=[{'node_id':f'n{i}','text':text,'native_ref':f'/blocks/{i}','kind':'paragraph','parent_id':None,
                'row':None,'column':None,'row_span':None,'column_span':None} for i,text in enumerate(['펌프 장치','압력 펌프','압력 40MPa 이상'])]
        return {'document_id':document_id,'source_path':str(source),'source_sha256':digest,'parse_path':str(native_path),
                'native_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest(),'parser_version':'controlled_fixture','nodes':nodes}
    class Model:
        async def generate(self,prompt,request,out):
            fields=request['output_schema']['properties']
            if 'root' in fields:
                return {'root':['n0','펌프 장치',None,None,['n0']],'items':[],'basis':'technical_table',
                        'basis_node_ids':['n0'],'integrated_scope':False,'scope_evidence_node_ids':[],'issues':[]}
            if 'additional' in fields:
                return {'additional':[['pump','n1','압력 펌프']],'types':[['root','equipment','required'],['pump','equipment','required']],
                        'relations':[['pump','root','component_of','explicit',['n1']]],'scopes':[['pump',['n2']]],'issues':[]}
            if 'facts' in fields:
                fragment=next(f[0] for f in request['fragments'] if f[1]=='n2')
                facts=[[fragment,['pump'],'operating_pressure','압력','number','gte','이상','40',
                        None if missing_unit_and_duplicate else 'MPa',[]]]
                if missing_unit_and_duplicate:facts.append([fragment,['root'],*facts[0][2:]])
                return {'facts':facts,'unresolved':[]}
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':['pump'],'role':'requirement_candidate',
                     'scope':'per_component','evidence_node_ids':['n2']} for a in request['attributes']]}
    monkeypatch.setattr(document_parser,'parse_document',parse)
    monkeypatch.setattr(tasks,'runner',lambda request:Model())
    forbidden=AsyncMock(side_effect=AssertionError('evaluation touched operational DB'))
    monkeypatch.setattr(flows,'start_execution',forbidden)
    workspace=tmp_path/'processing';workspace.mkdir()
    manifest={'run_id':'eval_fixture','mode':'standard_management','classification_code':'4110000000',
              'artifact_root':(tmp_path/'objects').as_uri(),
              'documents':[{'document_id':'pump_doc','notice_number':'N1','source_uri':source.as_uri(),'filename':source.name}]}
    with prefect_test_harness(server_startup_timeout=60):
        ref=await flows.extraction_evaluation_flow(manifest,str(workspace))
    data=json.loads(Path(ref['uri'].removeprefix('file://')).read_text())
    assert data['documents'][0]['attributes'][0]['value_raw']=='40'
    assert data['documents'][0]['attributes'][0]['unit_raw']=='MPa'
    assert data['documents'][0]['attributes'][0]['subject_ids']==['pump']
    assert data['documents'][0]['relations'][0]['kind']=='component_of'
    assert data['unavailable_documents']==[]
    assert len(data['documents'][0]['attributes'])==1
    if missing_unit_and_duplicate:
        attribute=data['documents'][0]['attributes'][0]
        assert attribute['unit_recovered_from_source'] is True
        assert len(attribute['merged_observations'])==2
        assert data['documents'][0]['unresolved_extraction']['semantic_resolution']['deduplicated']==1
        summary=json.loads((workspace/'processing/pump_doc/attributes/summary.json').read_text())
        assert summary['attributes']==1
        assert summary['numeric_comparisons']==1 and summary['unresolved_units']==0
    forbidden.assert_not_awaited()


async def test_worker_subprocess_keeps_failed_documents_and_cleans_owned_artifacts(tmp_path):
    from teoria_pipelines.domains.public_procurement.specification_processing import evaluation
    metadata=tmp_path/'notice.json';metadata.write_text(json.dumps({'code':'4321150102','notice':'fixture_notice'}))
    documents=[]
    for i in range(2):
        source=tmp_path/f'source_{i}.hwp';source.write_bytes(f'controlled source {i}'.encode())
        documents.append({'document_id':f'doc_{i}','notice_number':'fixture_notice','source_uri':source.as_uri(),'filename':source.name,
            'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'classification_code':'4321150102',
            'classification_evidence':{'path':str(metadata),'sha256':hashlib.sha256(metadata.read_bytes()).hexdigest(),
                'code_pointer':'/code','notice_pointer':'/notice'}})
    manifest=tmp_path/'evaluation.json';manifest.write_text(json.dumps({'cycle_id':'worker_smoke','documents':documents,
        'sample_size':2,'seed':1,'parser_python':'/bin/false','run_timeout_seconds':120}))
    directory=tmp_path/'summary';prepared=evaluation.prepare_cycle(manifest,directory)
    try:
        result=await evaluation.run_variant('worker_smoke','baseline',directory)
        assert result['development']['metrics']['failed_documents']==2
        assert result['development']['metrics']['requirement_cases_total']==0
        assert result['development']['usage']=={'available':False}
    finally:
        evaluation.abort_cycle('worker_smoke',directory)
    assert not Path(prepared['workspace']).exists()
    assert (tmp_path/'source_0.hwp').exists()
