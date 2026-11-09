import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from teoria.domains.goods.workflows import specifications as flows
from teoria.domains.goods.workflows import tasks
from teoria.domains.goods.data_processing import tasks as data_tasks
from teoria.domains.goods.contracts import SpecificationRun
from teoria.domains.goods.contracts import StandardArtifact
from teoria.domains.goods.contracts import ContextBinding
from teoria.domains.goods.contracts import PropertyBinding


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
    for name in ['verify_quality_evaluation','stage_original_documents','parse_documents','extract_entity_relations','extract_requirements','resolve_attribute_semantics','persist_extraction','resolve_dictionary','select_and_map_standard','persist_report','persist_document_results','persist_execution_receipt']:
        owner = data_tasks if hasattr(data_tasks, name) else tasks
        monkeypatch.setattr(owner,name,getattr(owner,name).fn)
    from teoria.domains.goods.normalization.meaning_proposals import expression_alignment as dictionary_alignment
    from teoria.domains.goods.normalization.meaning_proposals import expression_management as dictionary_incremental
    monkeypatch.setattr(dictionary_incremental,'collect_expression_proposals',AsyncMock(return_value=None))
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
    monkeypatch.setattr(dictionary_alignment,'_author_legacy_meanings',AsyncMock(return_value={
        'status':'completed','summary':{},'decisions':[]}))
    start=AsyncMock(return_value=None);complete=AsyncMock();failed=AsyncMock()
    monkeypatch.setattr(flows,'start_execution',start);monkeypatch.setattr(flows,'complete_execution',complete);monkeypatch.setattr(flows,'fail_execution',failed)
    return start,complete,failed

async def test_canonical_artifacts_are_separate_and_db_completion_is_last(tmp_path,undecorated):
    request=inputs(tmp_path)
    result=await flows.execute_specification_run(request)
    assert result.status=='completed'
    assert result.summary['applied']==1
    assert len(result.artifacts)==10
    root=tmp_path/'objects/specification_processing/fixture_run'
    assert sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())==sorted(['execution_receipt.json','documents/doc_1/result.json','source_term_alignment.json','dictionary_semantic_decisions.json','dictionary_bindings.json','dictionary_candidates.json','extracted.json','index.md','normalized.json','sources/doc_1.hwp'])
    for artifact in result.artifacts:
        path=Path(artifact.uri.removeprefix('file://'))
        assert path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==artifact.sha256
    undecorated[1].assert_awaited_once_with(result);undecorated[2].assert_not_awaited()

async def test_completed_replay_does_not_touch_inputs_or_model(tmp_path,undecorated):
    request=inputs(tmp_path);result=await flows.execute_specification_run(request)
    undecorated[0].return_value=result
    Path(request.documents[0].source_uri.removeprefix('file://')).unlink()
    assert await flows.execute_specification_run(request)==result


async def test_data_processing_can_skip_expression_registration_without_losing_source_artifacts(tmp_path,undecorated,monkeypatch):
    from teoria.domains.goods.normalization.meaning_proposals import expression_alignment as dictionary_alignment
    forbidden = AsyncMock(side_effect=AssertionError('expression registration must be optional'))
    monkeypatch.setattr(dictionary_alignment, 'align_dictionary', forbidden)
    request = inputs(tmp_path).model_copy(update={'use_expression_dictionary':False})
    result = await flows.execute_specification_run(request)
    forbidden.assert_not_awaited()
    assert result.status == 'completed' and result.summary['applied'] == 1
    assert result.summary['dictionary']['reason'] == 'expression_dictionary_disabled'
    assert result.summary['dictionary_operation_id'] is None
    keys = {artifact.key.rsplit('/',1)[-1] for artifact in result.artifacts}
    assert {'extracted.json','normalized.json','result.json','execution_receipt.json'} <= keys
    assert not keys.intersection({'dictionary_candidates.json','dictionary_bindings.json','source_term_alignment.json'})
    undecorated[1].assert_awaited_once_with(result)


def test_dictionary_disabled_cannot_approve_a_dictionary_backed_application_release(tmp_path):
    body = inputs(tmp_path, mode='standard_management').model_dump(mode='json')
    body.update(use_expression_dictionary=False, auto_approve_application_standard=True)
    with pytest.raises(ValueError, match='require expression dictionary'):
        SpecificationRun.model_validate(body)


async def test_pipeline_persists_three_level_policy_even_when_reusing_extraction(tmp_path,undecorated):
    from backend.tests.domains.goods.data_processing.extraction.test_composition_hierarchy import nested_document
    request=inputs(tmp_path)
    checkpoint=Path(request.extraction_checkpoint.uri.removeprefix('file://'))
    corpus=json.loads(checkpoint.read_text());document=corpus['documents'][0]
    graph=nested_document()
    document.update({key:graph[key] for key in ('composition_inventory','entities','relations','declared_quantities')})
    document['composition_hierarchy']={'schema_version':1,'max_primary_levels':99}  # Recompute stale policy.
    checkpoint.write_text(json.dumps(corpus));request.extraction_checkpoint.sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    result=await flows.execute_specification_run(request)
    assert result.status=='completed'
    folder=tmp_path/'objects/specification_processing/fixture_run'
    stored=json.loads((folder/'extracted.json').read_text())['documents'][0]
    assert stored['composition_hierarchy']['primary_entity_ids']==['goods','system','pc']
    assert stored['composition_hierarchy']['detail_entity_ids']==['cpu','chip']
    assert stored['attributes']==document['attributes']
    assert stored['relations']==document['relations']
    assert stored['declared_quantities']==document['declared_quantities']
    projected=json.loads((folder/'documents/doc_1/result.json').read_text())['extracted']['documents'][0]
    assert projected['composition_hierarchy']==stored['composition_hierarchy']

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


@pytest.mark.parametrize('failure',['partial_value','partial_span'])
async def test_checkpoint_cannot_ground_a_number_inside_a_larger_number(tmp_path,undecorated,failure):
    request=inputs(tmp_path);checkpoint=Path(request.extraction_checkpoint.uri.removeprefix('file://'))
    data=json.loads(checkpoint.read_text());document=data['documents'][0]
    text='CPU 116core' if failure=='partial_value' else 'CPU 16core / 116core'
    document['parsed_document']['nodes'][0]['text']=text
    if failure=='partial_span':
        start=text.rindex('16')
        document['attributes'][0]['evidence']['field_spans']={'value_raw':[[start,start+2]]}
    checkpoint.write_text(json.dumps(data));request.extraction_checkpoint.sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='numeric'):
        await flows.execute_specification_run(request)
    undecorated[1].assert_not_awaited();undecorated[2].assert_awaited_once()

async def test_management_without_selected_standard_preserves_unmapped_candidates(tmp_path,undecorated):
    request=inputs(tmp_path,'standard_management');request.standard=None
    request.auto_apply_source_literals=False
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
    import teoria.domains.goods.normalization.contracts
    source=tmp_path/'contract';source.mkdir();module=source/'__init__.py';module.write_text('policy = 1\n')
    monkeypatch.setattr(teoria.domains.goods.normalization.contracts,'__file__',str(module))
    first=flows.processor_revision();module.write_text('policy = 2\n')
    assert flows.processor_revision()!=first


def test_pinned_dictionary_resolution_policy_changes_invalidate_processing_revision(tmp_path,monkeypatch):
    from teoria.domains.goods.expression_links import snapshot_contracts as meaning_contracts
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
    stages=result.summary['processing_stages']
    assert stages['extraction']['status']=='completed'
    assert stages['expression_registration']['status']=='completed'
    assert stages['meaning']['status']=='review_required'
    assert stages['meaning']['counts']['unresolved_observations']==3
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


async def test_all_excluded_sources_are_not_reported_as_failed_extraction(tmp_path,undecorated):
    req=inputs(tmp_path)
    checkpoint=Path(req.extraction_checkpoint.uri.removeprefix('file://'))
    data=json.loads(checkpoint.read_text());document=data['documents'][0]
    data['documents']=[];data['unavailable_documents']=[{
        **{k:document.get(k) for k in ('document_id','notice_number','source')},
        'stage':'document_assessment','reason':'not_specification','disposition':'excluded'}]
    raw=json.dumps(data).encode();checkpoint.write_bytes(raw)
    req=SpecificationRun.model_validate({**req.model_dump(mode='json'),'extraction_checkpoint':{
        'uri':checkpoint.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()}})
    result=await flows.execute_specification_run(req)
    assert result.status=='completed'
    assert result.summary['failed_documents']==0 and result.summary['excluded_documents']==1
    assert result.document_results[0]['status']=='excluded'
    assert result.summary['processing_stages']['extraction']['status']=='excluded'
    assert result.summary['processing_stages']['meaning']['status']=='not_applicable'


async def test_execution_receipt_pins_verified_sources_and_artifact_checksums(tmp_path, undecorated):
    request = inputs(tmp_path)
    result = await flows.execute_specification_run(request)
    ref = next(a for a in result.artifacts if a.key.endswith('/execution_receipt.json'))
    receipt = json.loads(Path(ref.uri.removeprefix('file://')).read_bytes())
    assert receipt['sources'] == [{'document_id': 'doc_1', 'sha256': request.documents[0].sha256}]
    assert receipt['standard'] == request.standard.model_dump(mode='json')
    assert receipt['processor_revision'] == result.summary['processor_revision']
    assert receipt['quality_evaluation'] == 'not_attached'
    assert receipt['model']['immutable_identity_verified'] is False
    assert all(any(a.key == pinned['key'] and a.sha256 == pinned['sha256'] for a in result.artifacts) for pinned in receipt['artifacts'])


async def test_cli_release_guard_checks_approval_and_references_before_reading_originals(tmp_path, monkeypatch):
    from uuid import UUID
    import teoria.domains.goods.authoring_client as client_module
    request = inputs(tmp_path)
    request = request.model_copy(update={'application_release_id':UUID(int=1), 'dictionary_standard':request.standard,
        'dictionary_auto_approve':False,'dictionary_meaning_auto_approve':False})
    release = {'status':'approved','standard_kind':'extraction_draft',
        'standard_ref':request.standard.model_dump(mode='json'),
        'dictionary_ref':request.dictionary_standard.model_dump(mode='json'),
        'classification_code':request.classification_code}
    class API:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def application_standard(self,id):
            assert id == request.application_release_id
            return release
    monkeypatch.setattr(client_module,'GoodsAuthoringClient',API)
    # Approval checking has no reason to read the original document.
    Path(request.documents[0].source_uri.removeprefix('file://')).unlink()
    await flows.verify_application_release(request)
    for changes in [{'status':'deprecated'}, {'dictionary_ref':{}}, {'classification_code':None}]:
        original = dict(release)
        release.update(changes)
        with pytest.raises(ValueError, match='application_standard_reference_mismatch'):
            await flows.verify_application_release(request)
        release.clear();release.update(original)
    path = Path(request.standard.uri.removeprefix('file://'))
    path.write_text('{}')
    with pytest.raises(ValueError, match='application_standard_checksum_mismatch'):
        await flows.verify_application_release(request)


async def test_source_only_auto_application_preserves_literals_without_numeric_authority(tmp_path, undecorated):
    request=inputs(tmp_path,'standard_management');request.standard=None
    result=await flows.execute_specification_run(request)
    assert result.summary['applied']==1
    root=tmp_path/'objects/specification_processing/fixture_run'
    normalized=json.loads((root/'normalized.json').read_text())
    fact=normalized['attributes'][0]['facts'][0]
    assert fact['value']['text']=='16' and fact['value']['unit_raw']=='core'
    assert fact['value']['numeric_ordering_allowed'] is False
    assert fact['subject_ids']==['cpu'] and fact['semantic_scope']=='per_processor'
    standard=json.loads(Path(result.standard.uri.removeprefix('file://')).read_text())
    assert standard['published'] is False
    assert standard['definitions'][0]['approval_policy']=='grounded_source_literal_v1'


def test_source_auto_application_holds_unresolved_or_ungrounded_observations(tmp_path):
    from copy import deepcopy
    from teoria.domains.goods.normalization.application.extraction_rule_authoring import manage_standard
    request=inputs(tmp_path)
    original=json.loads(Path(request.extraction_checkpoint.uri.removeprefix('file://')).read_text())
    for field,value in [('semantic_scope','unknown'),('semantic_role','unknown'),('value_raw','160')]:
        corpus=deepcopy(original);corpus['documents'][0]['attributes'][0][field]=value
        standard,_,result=manage_standard(corpus,auto_apply_source_literals=True)
        assert not standard.bindings
        assert result['summary']['automatically_deferred']==1


async def test_quality_evaluation_rejects_tampered_or_wrong_model_evidence(tmp_path, undecorated):
    from teoria.domains.goods.contracts import StandardReference
    request = inputs(tmp_path).model_copy(update={"model": "current-model"})
    evidence = tmp_path / "cycle.json"
    evidence.write_text("{}")
    ref = StandardReference(uri=evidence.as_uri(), sha256="0" * 64)
    request = request.model_copy(update={"quality_evaluation": ref})
    with pytest.raises(ValueError, match="checksum_mismatch"):
        await tasks.verify_quality_evaluation(request, "revision")
    request = request.model_copy(update={"quality_evaluation": ref.model_copy(update={
        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()})})
    with pytest.raises(ValueError, match="quality_evaluation_blocked"):
        await tasks.verify_quality_evaluation(request, "revision")


async def test_verified_quality_evidence_is_pinned_in_execution_receipt(tmp_path, undecorated, monkeypatch):
    from copy import deepcopy
    from teoria.domains.goods.contracts import StandardReference
    from teoria.domains.goods.data_processing.evaluation.scoring import CASE_NAMES, ERROR_NAMES
    metrics = {name: 0 for name in ERROR_NAMES}
    for name in CASE_NAMES:
        metrics[name + "_cases_total"] = metrics[name + "_cases_found"] = 1
    score = {"metrics": metrics, "case_contract_version": 2, "documents": [
        {"document_id": "frozen_fixture", "missing_cases": []}], "independent_gold": True}
    revision = flows.processor_revision()
    cycle = {"status": "finished", "purpose": "extraction_improvement", "candidate_revision": revision,
             "comparison": {"decision": "accepted"}, "cleanup": {"status": "complete"},
             "sampling": {"freshness": "history_checked"}, "settings": {"model": "fixture-model"},
             "pipeline_tests_exit_code": 0, "results": {"candidate": {
                 split: deepcopy(score) for split in ("development", "validation", "regression")}}}
    evidence = tmp_path / "cycle.json"
    evidence.write_text(json.dumps(cycle))
    reference = StandardReference(uri=evidence.as_uri(), sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())
    request = inputs(tmp_path).model_copy(update={"model": "different-model", "quality_evaluation": reference})
    with pytest.raises(ValueError, match="model_mismatch"):
        await tasks.verify_quality_evaluation(request, revision)
    request = request.model_copy(update={"model": "fixture-model"})
    result = await flows.execute_specification_run(request)
    receipt_ref = next(a for a in result.artifacts if a.key.endswith("/execution_receipt.json"))
    receipt = json.loads(Path(receipt_ref.uri.removeprefix("file://")).read_bytes())
    assert receipt["schema_version"] == 2
    report = receipt["quality_evaluation"]
    assert report == result.summary["quality_evaluation"]
    assert report["status"] == "passed" and report["deployment_ready"] is False
    assert report["source"] == reference.model_dump(mode="json")
    assert any(a.sha256 == reference.sha256 for a in result.artifacts)
    assert receipt["model"]["immutable_identity_verified"] is False
