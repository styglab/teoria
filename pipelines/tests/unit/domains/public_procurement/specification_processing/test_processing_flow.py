import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from teoria_pipelines.domains.public_procurement.specification_processing import flows,tasks
from teoria_pipelines.domains.public_procurement.specification_processing.models import SpecificationRun,StandardArtifact,ContextBinding,PropertyBinding


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
    for name in ['stage_original_documents','parse_documents','extract_entity_relations','extract_requirements','resolve_attribute_semantics','persist_extraction','select_and_map_standard','persist_report']:
        monkeypatch.setattr(tasks,name,getattr(tasks,name).fn)
    start=AsyncMock(return_value=None);complete=AsyncMock();failed=AsyncMock()
    monkeypatch.setattr(flows,'start_execution',start);monkeypatch.setattr(flows,'complete_execution',complete);monkeypatch.setattr(flows,'fail_execution',failed)
    return start,complete,failed

async def test_canonical_artifacts_are_separate_and_db_completion_is_last(tmp_path,undecorated):
    request=inputs(tmp_path)
    result=await flows.execute_specification_run(request)
    assert result.status=='completed'
    assert result.summary['applied']==1
    assert len(result.artifacts)==4
    root=tmp_path/'objects/specification_processing/fixture_run'
    assert sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())==['extracted.json','index.md','normalized.json','sources/doc_1.hwp']
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
    import teoria_goods_normalization
    source=tmp_path/'contract';source.mkdir();module=source/'__init__.py';module.write_text('policy = 1\n')
    monkeypatch.setattr(teoria_goods_normalization,'__file__',str(module))
    first=flows.processor_revision();module.write_text('policy = 2\n')
    assert flows.processor_revision()!=first
