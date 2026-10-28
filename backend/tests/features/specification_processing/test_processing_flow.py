import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from teoria.features.specification_processing import flows,tasks
from teoria.features.specification_processing.models import SpecificationRun,StandardArtifact,ContextBinding,PropertyBinding


def inputs(tmp_path,mode='document_processing'):
    source=tmp_path/'source.hwp';source.write_bytes(b'unit source fixture')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    corpus={'classification_code':'4321150102','documents':[{'document_id':'doc_1','source':{'path':'sources/doc_1.hwp','sha256':digest},
        'parser':{'version':'fixture'},'parsed_document':{'nodes':[{'node_id':'n','kind':'paragraph','text':'CPU 16core'}]},
        'entities':[{'id':'root','name':'서버','kind':'equipment'},{'id':'cpu','name':'CPU','kind':'equipment'}],
        'relations':[{'id':'r','source_id':'cpu','target_id':'root','kind':'component_of'}],
        'attributes':[{'id':'a','subject_ids':['cpu'],'property_key':'core_count','data_type':'number','value_raw':'16','unit_raw':'core','operator':'eq','operator_raw':None,'qualifiers_raw':[],
            'semantic_role':'requirement_candidate','semantic_scope':'per_processor','evidence':{'node_id':'n'}}],
        'extraction_status':'extracted'}],'unavailable_documents':[]}
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(corpus))
    standard=StandardArtifact(rule_set='server',version='fixture_v1',classification_code='4321150102',definitions=[{'id':'cpu_cores_per_processor','label':'CPU당 코어 수'}],bindings=[ContextBinding(target_types=['processor'],property_key='core_count',unit_context='core',data_type='number',role='requirement_candidate',semantic_scope='per_processor',properties=[PropertyBinding(property_id='cpu_cores_per_processor',rule_kind='server_literal')])])
    seed=tmp_path/'standard.json';seed.write_text(standard.model_dump_json())
    return SpecificationRun(run_id='fixture_run',mode=mode,classification_code='4321150102',artifact_root=(tmp_path/'objects').as_uri(),
        documents=[{'document_id':'doc_1','notice_number':'fixture_notice','source_uri':source.as_uri(),'filename':'source.hwp','sha256':digest}],
        extraction_checkpoint={'uri':checkpoint.as_uri(),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()},
        standard={'uri':seed.as_uri(),'sha256':hashlib.sha256(seed.read_bytes()).hexdigest()})

@pytest.fixture
def undecorated(monkeypatch):
    # Exercise the exact operational task bodies without starting an orchestration server.
    for name in ['stage_original_documents','parse_documents','extract_entity_relations','extract_requirements','resolve_attribute_semantics','persist_extraction','resolve_dictionary','select_and_map_standard','persist_report']:
        monkeypatch.setattr(tasks,name,getattr(tasks,name).fn)
    from teoria.features.specification_processing.normalization import dictionary_alignment
    class DictionaryAPI:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def resolve_dictionary_meanings(self,source_entry_ids,classification_code=None):
            return {'policy_version':'fixture','items':[]}
        async def dictionary(self,operation_id,payload):
            from uuid import UUID
            return {'operation_id':operation_id,'policy_version':'fixture','approval_mode':'automatic_policy',
                'status':'completed','summary':{'approved':len(payload['candidates']),'reused':0,'held':0,'proposed':0},
                'decisions':[{'candidate_key':c['candidate_key'],'origin_ref':c['origin_ref'],'status':'approved',
                              'reason':'controlled_fixture','entry_id':str(UUID(int=i+1))} for i,c in enumerate(payload['candidates'])]}
    monkeypatch.setattr(dictionary_alignment,'GoodsAuthoringClient',DictionaryAPI)
    monkeypatch.setattr(dictionary_alignment,'author_dictionary_meanings',AsyncMock(return_value={
        'status':'completed','summary':{},'decisions':[]}))
    start=AsyncMock(return_value=None);complete=AsyncMock();failed=AsyncMock()
    monkeypatch.setattr(flows,'start_execution',start);monkeypatch.setattr(flows,'complete_execution',complete);monkeypatch.setattr(flows,'fail_execution',failed)
    return start,complete,failed

async def test_canonical_artifacts_are_separate_and_db_completion_is_last(tmp_path,undecorated):
    request=inputs(tmp_path)
    result=await flows.execute_specification_run(request)
    assert result.status=='completed'
    assert result.summary['applied']==1
    assert len(result.artifacts)==8
    root=tmp_path/'objects/specification_processing/fixture_run'
    assert sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())==sorted(['source_term_alignment.json','dictionary_semantic_decisions.json','dictionary_bindings.json','dictionary_candidates.json','extracted.json','index.md','normalized.json','sources/doc_1.hwp'])
    for artifact in result.artifacts:
        path=Path(artifact.uri.removeprefix('file://'))
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==artifact.sha256
    undecorated[1].assert_awaited_once_with(result);undecorated[2].assert_not_awaited()

async def test_completed_replay_does_not_touch_inputs_or_model(tmp_path,undecorated):
    request=inputs(tmp_path);result=await flows.execute_specification_run(request)
    undecorated[0].return_value=result
    Path(request.documents[0].source_uri.removeprefix('file://')).unlink()
    assert await flows.execute_specification_run(request)==result

async def test_standard_management_writes_only_draft_proposal(tmp_path,undecorated):
    request=inputs(tmp_path,'standard_management')
    result=await flows.execute_specification_run(request)
    assert result.standard is not None
    standard=json.loads(Path(result.standard.uri.removeprefix('file://')).read_text())
    assert standard['published'] is False and standard['status']=='pipeline_selected_draft'
    assert (tmp_path/'objects/specification_processing/fixture_run/meaning_candidates.json').exists()
    assert result.summary['human_approval_required'] is False

async def test_source_mismatch_fails_without_completion_checkpoint(tmp_path,undecorated):
    request=inputs(tmp_path);request.documents[0].sha256='0'*64
    with pytest.raises(ValueError,match='source checksum'):
        await flows.execute_specification_run(request)
    undecorated[1].assert_not_awaited();undecorated[2].assert_awaited_once()

async def test_untrusted_checkpoint_cannot_change_source_subjects(tmp_path,undecorated):
    request=inputs(tmp_path);checkpoint=Path(request.extraction_checkpoint.uri.removeprefix('file://'))
    data=json.loads(checkpoint.read_text());data['documents'][0]['attributes'][0]['subject_ids']=['invented']
    checkpoint.write_text(json.dumps(data));request.extraction_checkpoint.sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='subject'):
        await flows.execute_specification_run(request)
    undecorated[1].assert_not_awaited()

async def test_management_without_selected_standard_preserves_unmapped_candidates(tmp_path,undecorated):
    request=inputs(tmp_path,'standard_management');request.standard=None
    result=await flows.execute_specification_run(request)
    assert result.status=='partial' and result.summary['automatically_deferred']==1
    draft=json.loads(Path(result.standard.uri.removeprefix('file://')).read_text())
    assert draft['rule_set']=='source_only' and draft['definitions']==[]
    artifact=next(a for a in result.artifacts if a.key.endswith('/meaning_candidates.json'))
    candidates=json.loads(Path(artifact.uri.removeprefix('file://')).read_text())
    assert candidates['summary']['observations']==1
    assert candidates['candidates'][0]['target_type_candidate']=='equipment:CPU'
    undecorated[1].assert_awaited_once_with(result)


def test_contract_policy_changes_invalidate_processing_revision(tmp_path,monkeypatch):
    import teoria.features.goods_normalization.contracts
    source=tmp_path/'contract';source.mkdir();module=source/'__init__.py';module.write_text('policy = 1\n')
    monkeypatch.setattr(teoria.features.goods_normalization.contracts,'__file__',str(module))
    first=flows.processor_revision();module.write_text('policy = 2\n')
    assert flows.processor_revision()!=first


def test_pinned_dictionary_resolution_policy_changes_invalidate_processing_revision(tmp_path,monkeypatch):
    from teoria.features.semantic_modeling.goods_dictionary import meaning_contracts
    module=tmp_path/'meaning_contracts.py';module.write_text('policy = 1\n')
    monkeypatch.setattr(meaning_contracts,'__file__',str(module))
    before=flows.processor_revision();module.write_text('policy = 2\n')
    assert flows.processor_revision()!=before



async def test_dictionary_is_an_existing_stage_and_applies_refs_without_changing_observations(tmp_path,undecorated):
    request=inputs(tmp_path,'standard_management');request.classification_code=None;request.standard=None
    checkpoint=Path(request.extraction_checkpoint.uri.removeprefix('file://'))
    data=json.loads(checkpoint.read_text());data['classification_code']=None
    data['documents'][0]['attributes'][0]['property_raw']='코어 수'
    data['documents'][0]['parsed_document']['nodes'][0]['text']='서버 CPU 코어 수 16core'
    checkpoint.write_text(json.dumps(data));request.extraction_checkpoint.sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    result=await flows.execute_specification_run(request)
    root=tmp_path/'objects/specification_processing/fixture_run'
    aligned=json.loads((root/'source_term_alignment.json').read_text())
    normalized=json.loads((root/'normalized.json').read_text())
    assert result.summary['dictionary']['approved']==3
    assert aligned['documents'][0]['entities'][1]['source_term_ref'].startswith('source_term:')
    assert aligned['documents'][0]['attributes'][0]['source_term_ref'].startswith('source_term:')
    assert 'type_ref' not in aligned['documents'][0]['entities'][1]
    assert 'characteristic_ref' not in aligned['documents'][0]['attributes'][0]
    assert aligned['documents'][0]['attributes'][0]['value_raw']=='16'
    assert aligned['documents'][0]['review_status']=='proposed'
    assert normalized['source_term_alignment']['artifact']['uri'].endswith('/source_term_alignment.json')
    assert normalized['source_term_alignment']['human_review_performed'] is False
    assert normalized['dictionary_meanings']['summary']=={'unresolved':3}
    assert all(a['meaning_status']=='unresolved' for a in normalized['dictionary_meanings']['documents'][0]['attributes'])
    undecorated[1].assert_awaited_once_with(result)


def test_retired_dictionary_mode_and_graph_entry_are_rejected(tmp_path):
    body=inputs(tmp_path).model_dump(mode='json')
    body['mode']='dictionary_authoring'
    with pytest.raises(ValueError):SpecificationRun.model_validate(body)
    body['mode']='standard_management';body['classification_code']=None;body['standard']=None
    assert SpecificationRun.model_validate(body).dictionary_auto_approve is True
    body['dictionary_graphs']={'uri':'file:///tmp/legacy.yaml','sha256':'a'*64}
    with pytest.raises(ValueError):SpecificationRun.model_validate(body)
