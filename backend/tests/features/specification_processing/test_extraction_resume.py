"""A failed semantic batch must not rerun verified parsing/composition/attributes."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from teoria.features.specification_processing import flows,tasks
from teoria.features.specification_processing.models import SpecificationRun


async def test_resume_after_semantic_timeout_reuses_verified_upstream_results(tmp_path,monkeypatch):
    from teoria.features.specification_processing.parsing import document_parser,document_assessment
    from teoria.features.specification_processing.extraction import entity_relation_extraction
    source=tmp_path/'source.pdf';source.write_bytes(b'fixture source')
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    request=SpecificationRun(run_id='first',mode='standard_management',model='pinned_model',
        artifact_root=(tmp_path/'objects').as_uri(),dictionary_auto_approve=False,dictionary_meaning_auto_approve=False,
        documents=[{'document_id':'doc','filename':'source.pdf','source_uri':source.as_uri(),'sha256':source_hash}])
    calls={'parse':0,'composition':0,'attributes':0,'semantics':0};fail_semantics=True
    expected={'document_id':'doc','entities':[{'id':'root','name':'서버','kind':'equipment','evidence':[]},
               {'id':'cpu','name':'CPU','kind':'equipment','evidence':[{'node_id':'n','quote':'CPU'}]}],
               'relations':[{'id':'r','source_id':'cpu','target_id':'root','kind':'component_of','basis':'explicit'}],
               'requirements':[],'declared_quantities':[],'inventory_ids':['cpu'],
               'composition_inventory':{'root_id':'root','item_ids':['cpu']}}
    async def parse(path,out,document_id,parser_python):
        calls['parse']+=1;out.write_text(json.dumps({'sha256':source_hash,'parser_version':'fixture'}))
        return {'document_id':document_id,'source_path':str(path),'parse_path':str(out),
                'source_sha256':source_hash,'native_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
                'nodes':[{'node_id':'n','kind':'paragraph','text':'CPU 16core','parent_id':None,'native_ref':'/blocks/1'}],
                'parser_version':'fixture'}
    async def composition(document,out,runner,*,checkpoints=None):
        calls['composition']+=1
        for name,value in {'document.json':document,'graph.json':deepcopy(expected),'inventory.json':{},
                           'summary.json':{'status':'needs_review'},'status.json':{'stage':'complete'},
                           'inventory_validation.json':{'errors':[]},'details_validation.json':{'errors':[]},
                           'held_relations.json':[],'identifier_projection.json':{'aliases':{}}}.items():
            await tasks.save(out/name,value)
    class Model:
        async def generate(self,prompt,context,path,**kwargs):
            if 'fragments' in context:
                calls['attributes']+=1
                return {'facts':[[context['fragments'][0][0],['cpu'],'core_count',None,'number','eq',None,'16','core',[]]],'unresolved':[]}
            calls['semantics']+=1
            if fail_semantics:raise TimeoutError('controlled semantic failure')
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':['cpu'],'role':'requirement_candidate',
                    'scope':'per_processor','evidence_node_ids':['n'],'source_quote':'CPU 16core',
                    'property_label':'코어 수','description':False} for a in context['attributes']], 'composition_links':[]}
    monkeypatch.setattr(document_parser,'parse_document',parse)
    monkeypatch.setattr(document_parser,'parser_runtime_identity',AsyncMock(return_value={'version':'fixture','source_sha256':'pinned'}))
    monkeypatch.setattr(document_assessment,'assess_document',AsyncMock(return_value={
        'excluded':False,'status':'classified','node_roles':{'n':'technical_requirement'}}))
    monkeypatch.setattr(entity_relation_extraction,'extract_entity_relations',composition)
    monkeypatch.setattr(tasks,'runner',lambda request:Model())
    async def run(folder):
        folder.mkdir()
        await tasks.stage_original_documents.fn(request,str(folder))
        await tasks.parse_documents.fn(request,str(folder))
        await tasks.extract_entity_relations.fn(request,str(folder))
        await tasks.extract_requirements.fn(request,str(folder))
        await tasks.resolve_attribute_semantics.fn(request,str(folder))
        return await tasks.load(folder/'processing/doc/attributes/attribute_graph.json')
    first=await run(tmp_path/'first')
    assert calls=={'parse':1,'composition':1,'attributes':1,'semantics':2}
    assert first['attributes'][0]['semantic_role']=='unknown'
    fail_semantics=False
    request=request.model_copy(update={'run_id':'retry'})
    final=await run(tmp_path/'retry')
    assert calls=={'parse':1,'composition':1,'attributes':1,'semantics':3}
    assert final['attributes'][0]['subject_ids']==['cpu']
    assert final['attributes'][0]['semantic_role']=='requirement_candidate'
    assert final['attributes'][0]['property_label']=='코어 수'
    for key in ('entities','relations','inventory_ids','composition_inventory','declared_quantities'):
        assert final[key]==expected[key]
    fail_semantics=True
    request=request.model_copy(update={'run_id':'completed_reuse'})
    replayed=await run(tmp_path/'completed_reuse')
    assert calls=={'parse':1,'composition':1,'attributes':1,'semantics':3}
    assert replayed['attributes']==final['attributes']


async def test_evaluation_forces_fresh_extraction_even_when_caller_requests_reuse(tmp_path,monkeypatch):
    extract=AsyncMock(return_value=({'uri':'file:///fixture'},False));monkeypatch.setattr(flows,'extract_documents',extract)
    request={'run_id':'eval','mode':'standard_management','model':'pinned_model','artifact_root':tmp_path.as_uri(),
             'reuse_stage_checkpoints':True,'documents':[{'document_id':'doc','filename':'x.pdf','source_uri':'file:///x.pdf'}]}
    await flows.extraction_evaluation_flow.fn(request,str(tmp_path))
    assert extract.await_args.args[0].reuse_stage_checkpoints is False


async def test_timeout_in_details_does_not_regenerate_verified_inventory(tmp_path):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import extract_entity_relations
    from teoria.features.specification_processing.storage.extraction_checkpoints import ExtractionCheckpoints
    from teoria.features.specification_processing.storage.artifact_store import FileArtifactStore
    values={'root':'서버 1 set','list':'장비의 구성','cpu':'CPU 2개'}
    document={'document_id':'doc','source_sha256':'original','nodes':[
        {'node_id':key,'text':text,'kind':'paragraph','native_ref':'/'+key,
         'parent_id':None,'row':None,'column':None,'row_span':None,'column_span':None}
        for key,text in values.items()]}
    inventory={'root':['root','서버','1','set',['root']],'basis':'configuration_list',
               'basis_node_ids':['list'],'items':[['cpu','cpu','CPU','2','개',['cpu']]],
               'integrated_scope':True,'scope_evidence_node_ids':['root','list'],'issues':[]}
    calls={'inventory':0,'details':0};failed=True
    class Model:
        async def generate(self,prompt,request,path):
            if 'inventory' not in request:
                calls['inventory']+=1;return inventory
            calls['details']+=1
            if failed:raise TimeoutError('controlled detail failure')
            return {'additional':[],'types':[['root','equipment','required'],['cpu','equipment','required']],
                    'relations':[['cpu','root','component_of','explicit',['list','cpu']]],'scopes':[],'issues':[]}
    cache=await ExtractionCheckpoints.create(FileArtifactStore(tmp_path/'objects'),'pinned_model')
    with pytest.raises(TimeoutError):await extract_entity_relations(document,tmp_path/'first',Model(),checkpoints=cache)
    failed=False
    await extract_entity_relations(document,tmp_path/'retry',Model(),checkpoints=cache)
    assert calls=={'inventory':1,'details':2}
    graph=json.loads((tmp_path/'retry/graph.json').read_text())
    assert next(q['value_raw'] for q in graph['declared_quantities'] if q['entity_id']=='cpu')=='2'


async def test_only_incomplete_semantic_batch_is_retried_after_validation_failure(tmp_path):
    from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics
    from teoria.features.specification_processing.storage.extraction_checkpoints import ExtractionCheckpoints
    from teoria.features.specification_processing.storage.artifact_store import FileArtifactStore
    text='CPU 16core'
    document={'source_sha256':'source','nodes':[{'node_id':str(i),'kind':'paragraph','text':text} for i in range(46)]}
    graph={'entities':[{'id':'cpu','name':'CPU','kind':'equipment'}],'relations':[]}
    attributes=[{'id':str(i),'subject_ids':['cpu'],'property_key':'cores_'+str(i),'property_raw':None,
                 'data_type':'number','operator':'eq','value_raw':'16','unit_raw':'core','qualifiers_raw':[],
                 'evidence':{'node_id':str(i),'char_start':0,'char_end':len(text)}} for i in range(46)]
    calls=[];fail=True
    class Model:
        async def generate(self,prompt,request,path):
            calls.append(len(request['attributes']))
            if fail and len(request['attributes'])==1:return {'resolutions':[]}
            return {'resolutions':[{'attribute_id':a['id'],'subject_ids':['cpu'],'role':'requirement_candidate',
                    'scope':'per_item','evidence_node_ids':[a['evidence']['node_id']],'source_quote':text}
                    for a in request['attributes']]}
    cache=await ExtractionCheckpoints.create(FileArtifactStore(tmp_path/'objects'),'pinned_model')
    first=await resolve_attribute_semantics(document,deepcopy(graph),deepcopy(attributes),Model(),tmp_path/'first',checkpoints=cache)
    assert first['failed_batches']==1 and first['model_failures']==0 and sorted(calls)==[1,1,45]
    fail=False
    final=await resolve_attribute_semantics(document,deepcopy(graph),deepcopy(attributes),Model(),tmp_path/'retry',checkpoints=cache)
    assert final['failed_batches']==0 and final['cached_batches']==1
    assert sorted(calls)==[1,1,1,45]

async def test_cpu_parser_budget_is_separate_from_concurrent_model_assessment(tmp_path,monkeypatch):
    import asyncio
    from teoria.features.specification_processing.parsing import document_parser,document_assessment
    source=tmp_path/'source.pdf';source.write_bytes(b'fixture')
    request=SpecificationRun(run_id='parse_budget',mode='standard_management',model='pinned_model',
        artifact_root=(tmp_path/'objects').as_uri(),reuse_stage_checkpoints=False,concurrency=4,
        documents=[{'document_id':f'doc{i}','filename':'source.pdf','source_uri':source.as_uri()} for i in range(4)])
    active=peak=assessing=0;two_assessments=asyncio.Event()
    async def parse(path,native,id,python):
        nonlocal active,peak
        active+=1;peak=max(active,peak)
        try:
            await asyncio.sleep(0)
            return {'document_id':id,'nodes':[]}
        finally:active-=1
    async def assess(document,model,folder):
        nonlocal assessing
        assessing+=1
        if assessing>=2:two_assessments.set()
        await two_assessments.wait()
        assessing-=1
        return {'excluded':False,'status':'classified','node_roles':{}}
    monkeypatch.setattr(document_parser,'parse_document',parse)
    monkeypatch.setattr(document_assessment,'assess_document',assess)
    monkeypatch.setattr(tasks,'runner',lambda request:object())
    folder=tmp_path/'work';folder.mkdir()
    await tasks.stage_original_documents.fn(request,str(folder))
    await asyncio.wait_for(tasks.parse_documents.fn(request,str(folder)),2)
    assert peak==1 and two_assessments.is_set()
    entries=await tasks.load(folder/'work.json')
    assert not any(entry.get('failure') for entry in entries)
