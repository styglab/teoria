"""Producer → portable JSON → Pipeline consumer, using explicit synthetic source cases."""
from copy import deepcopy
from pathlib import Path
from uuid import UUID
import hashlib
import json
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from teoria_goods_normalization import NormalizationProfile,NormalizationPackage,canonical_bytes,checksum
from teoria.domains.goods.normalization.compiler import compile_package
from teoria_pipelines.domains.public_procurement.specification_processing.standardization.profile_application import apply_profile
from teoria_pipelines.domains.public_procurement.specification_processing import flows,tasks
from teoria_pipelines.domains.public_procurement.specification_processing.models import SpecificationRun


def uid(n):return str(UUID(int=n))


def example():
    ontology={'namespace':'goods_test','version':'test_1','objects':[
        {'business_object_id':uid(101),'concept_id':uid(1),'stable_key':'goods_test.memory','properties':[
            {'concept_id':uid(2),'stable_key':'goods_test.memory.capacity','value_type':'decimal','unit':'GB'},
            {'concept_id':uid(3),'stable_key':'goods_test.memory.module_count','value_type':'integer','unit':'개'}]},
        {'business_object_id':uid(102),'concept_id':uid(4),'stable_key':'goods_test.server','properties':[]}],
        'relationships':[{'concept_id':uid(5),'stable_key':'goods_test.has_memory','source_object_id':uid(102),'target_object_id':uid(101)}]}
    base={'target_concept_id':uid(1),'property_concept_id':uid(2),'source_property_keys':['capacity'],
          'roles':['requirement_candidate'],'scopes':['per_component','per_module'],'value_type':'number',
          'units':[{'source_unit':'GB','canonical_unit':'GB'}]}
    profile=NormalizationProfile.model_validate({'profile_key':'server_memory','version':'test_1','classification_code':'4321150102',
        'ontology':{'version_id':uid(100),'namespace':ontology['namespace'],'version':ontology['version'],'checksum':checksum(ontology)},
        'entities':[{'rule_id':'memory','aliases':['RAM','메모리'],'concept_id':uid(1)},
                    {'rule_id':'server','aliases':['서버'],'concept_id':uid(4)}],
        'requirements':[{**base,'rule_id':'capacity'},
            {**base,'rule_id':'count','source_property_keys':['quantity'],'property_concept_id':uid(3),
             'scopes':['per_component','system_total'],'units':[{'source_unit':'개','canonical_unit':'개'}]},
            {**base,'rule_id':'supported_capacity','roles':['supported_capability'],'scopes':['support_limit'],
             'units':[{'source_unit':'TB','canonical_unit':'GB','multiplier':'1000'}]}],
        'relations':[{'rule_id':'memory_part','source_kind':'component_of','relationship_concept_id':uid(5),'reverse':True}]})
    text='서버 / RAM 64GB 이상 / 메모리 모듈당 32GB, 4개 / 최대 1TB 지원'
    attrs=[]
    for i,(target,key,value,unit,op,role,scope) in enumerate([
        ('m1','capacity','64','GB','gte','requirement_candidate','per_component'),
        ('m2','capacity','32','GB','eq','requirement_candidate','per_module'),
        ('m2','quantity','4','개','eq','requirement_candidate','system_total'),
        ('m3','capacity','1','TB','lte','supported_capability','support_limit')]):
        attrs.append({'id':f'a{i}','subject_ids':[target],'property_key':key,'value_raw':value,'unit_raw':unit,'operator':op,
                      'operator_raw':None,'qualifiers_raw':[],'data_type':'number','semantic_role':role,'semantic_scope':scope,'evidence':{'node_id':'n'}})
    doc={'document_id':'doc','source':{'sha256':hashlib.sha256(b'controlled source').hexdigest()},
         'parsed_document':{'nodes':[{'node_id':'n','text':text}]},
         'entities':[{'id':id,'name':name,'kind':'equipment','evidence':[{'node_id':'n'}]} for id,name in [('root','서버'),('m1','RAM'),('m2','메모리'),('m3','메모리')]],
         'relations':[{'id':'r','source_id':'m1','target_id':'root','kind':'component_of','evidence':[{'node_id':'n'}]},
                      {'id':'scope','source_id':'m2','target_id':'root','kind':'in_procurement_scope','evidence':[{'node_id':'n'}]}],
         'attributes':attrs,'extraction_status':'extracted','parser':{'version':'controlled_fixture'}}
    return profile,ontology,{'classification_code':'4321150102','documents':[doc],'unavailable_documents':[]}


def package(profile,ontology):return compile_package(profile,ontology,revision_id=UUID(int=200),approval_actor='test_reviewer')


def test_three_memory_meanings_survive_platform_to_pipeline_serialization():
    profile,ontology,corpus=example();exported=package(profile,ontology)
    loaded=NormalizationPackage.model_validate_json(canonical_bytes(exported))
    result,candidates=apply_profile(corpus,loaded,run_id='run_1')
    facts=result['documents'][0]['requirements']
    assert [(f['value']['decimal'],f['value']['unit'],f['operator'],f['role'],f['semantic_scope']) for f in facts]==[
        ('64','GB','gte','requirement_candidate','per_component'),('32','GB','eq','requirement_candidate','per_module'),
        ('4','개','eq','requirement_candidate','system_total'),('1000','GB','lte','supported_capability','support_limit')]
    assert not any(f['value']['decimal']=='128' for f in facts)
    assert facts[-1]['value_raw']=='1' and facts[-1]['unit_raw']=='TB'
    entities={r['source_entity_id']:r for r in result['documents'][0]['entities']}
    assert entities['m2']['observation_id']!=entities['m3']['observation_id']
    relation=result['documents'][0]['relations'][0]
    assert relation['source_observation_id']==entities['root']['observation_id']
    assert relation['target_observation_id']==entities['m1']['observation_id']
    assert len(result['documents'][0]['relations'])==1
    assert candidates['candidates'][0]['kind']=='relation' # scope membership is not converted to a physical part
    changed=apply_profile(corpus,loaded,run_id='run_2')[0]
    assert changed['documents'][0]['entities'][0]['observation_id']!=entities['root']['observation_id']


@pytest.mark.parametrize('change',['checksum','wrong_owner','unknown_concept','wrong_type','conversion'])
def test_invalid_package_and_semantic_contracts_are_rejected(change):
    profile,ontology,_=example();data=profile.model_dump(mode='json')
    if change=='checksum':
        exported=package(profile,ontology).model_dump(mode='json');exported['approval_actor']='forged'
        with pytest.raises(ValidationError,match='checksum'):NormalizationPackage.model_validate(exported)
        return
    if change=='wrong_owner':data['requirements'][0]['target_concept_id']=uid(4)
    if change=='unknown_concept':data['entities'][0]['concept_id']=uid(999)
    if change=='wrong_type':data['requirements'][0].update(value_type='text',units=[])
    if change=='conversion':data['requirements'][-1]['units'][0]['multiplier']='1024'
    with pytest.raises(ValueError):package(NormalizationProfile.model_validate(data),ontology)


@pytest.mark.parametrize('change,reason',[('unit','unsupported_source_unit'),('role','no_requirement_rule'),
    ('scope','no_requirement_rule'),('grounding','source_condition_mismatch'),('ambiguity','ambiguous_requirement_rule')])
def test_unresolved_meanings_are_preserved_as_candidates(change,reason):
    profile,ontology,corpus=example();a=corpus['documents'][0]['attributes'][0]
    if change=='unit':
        a['unit_raw']='G';corpus['documents'][0]['parsed_document']['nodes'][0]['text']+=' / 64G'
    if change=='role':a['semantic_role']='existing_reference'
    if change=='scope':a['semantic_scope']='system_total'
    if change=='grounding':a['value_raw']='9999'
    if change=='ambiguity':
        data=profile.model_dump(mode='json');rule=deepcopy(data['requirements'][0]);rule['rule_id']='overlap';data['requirements'].append(rule)
        profile=NormalizationProfile.model_validate(data)
    result,candidates=apply_profile(corpus,package(profile,ontology),run_id='test')
    assert result['attributes'][0]['reason']==reason
    assert any(c.get('attribute_id')=='a0' and c.get('reason')==reason for c in candidates['candidates'])


def test_count_types_and_classification_are_validated_without_losing_source():
    profile,ontology,corpus=example();exported=package(profile,ontology)
    data=deepcopy(corpus);data['classification_code']='4321150701'
    with pytest.raises(ValueError,match='classification'):apply_profile(data,exported,run_id='test')
    a=corpus['documents'][0]['attributes'][2];a['value_raw']='4.5'
    corpus['documents'][0]['parsed_document']['nodes'][0]['text']+=' / 4.5개'
    normalized,candidates=apply_profile(corpus,exported,run_id='test')
    assert normalized['attributes'][2]['reason']=='non_integral_count'
    assert any(c.get('value_raw')=='4.5' for c in candidates['candidates'])


def test_validated_inventory_count_uses_only_its_explicit_target_scope():
    profile,ontology,corpus=example();a=corpus['documents'][0]['attributes'][2]
    a.pop('semantic_role');a.pop('semantic_scope');a['origin']='validated_inventory_quantity'
    a['evidence']={'source_node_ids':['n'],'scope':'explicit inventory target only'}
    result,_=apply_profile(corpus,package(profile,ontology),run_id='test')
    assert result['attributes'][2]['facts'][0]['semantic_scope']=='per_component'
    a['semantic_scope']='unknown'
    result,_=apply_profile(corpus,package(profile,ontology),run_id='test')
    assert result['attributes'][2]['status']=='automatically_deferred'


async def test_operational_standard_management_uses_package_and_saves_only_canonical_artifacts(tmp_path,monkeypatch):
    profile,ontology,corpus=example();source=tmp_path/'source.hwp';source.write_bytes(b'controlled source')
    corpus['documents'][0]['notice_number']='test_notice'
    exported=tmp_path/'package.json';exported.write_bytes(canonical_bytes(package(profile,ontology)))
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(corpus))
    request=SpecificationRun(run_id='profile_run',mode='standard_management',classification_code='4321150102',
        artifact_root=(tmp_path/'objects').as_uri(),documents=[{'document_id':'doc','source_uri':source.as_uri(),'filename':source.name}],
        standard={'uri':exported.as_uri(),'sha256':hashlib.sha256(exported.read_bytes()).hexdigest()},
        extraction_checkpoint={'uri':checkpoint.as_uri(),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()})
    for name in ['stage_original_documents','persist_extraction','select_and_map_standard','persist_report']:
        monkeypatch.setattr(tasks,name,getattr(tasks,name).fn)
    monkeypatch.setattr(flows,'start_execution',AsyncMock(return_value=None))
    complete=AsyncMock();monkeypatch.setattr(flows,'complete_execution',complete);monkeypatch.setattr(flows,'fail_execution',AsyncMock())
    result=await flows.execute_specification_run(request)
    normalized=json.loads((tmp_path/'objects/specification_processing/profile_run/normalized.json').read_text())
    assert normalized['summary']['applied']==4 and result.standard.uri==exported.as_uri()
    assert result.status=='partial' and normalized['extraction_ref']['sha256']
    assert len(result.artifacts)==5
    report=(tmp_path/'objects/specification_processing/profile_run/index.md').read_text()
    assert 'support_limit' in report and '1000 GB' in report
    complete.assert_awaited_once()


def candidate_case():
    """Unmapped capacity spelling, still linked to a known Memory target."""
    profile, ontology, corpus = example()
    corpus['documents'][0]['attributes'][0]['property_key'] = 'capacity_bytes'
    corpus['documents'][0]['attributes'][0]['property_raw'] = '용량'
    _, proposals = apply_profile(corpus, package(profile, ontology), run_id='candidate_test')
    from teoria_goods_normalization.candidates import CandidateBundle
    bundle = CandidateBundle.model_validate(proposals['bundle'])
    group = next(g for g in bundle.groups if g.context.kind == 'requirement')
    return profile, ontology, corpus, bundle, group


def test_candidates_roundtrip_deduplicate_and_build_compatible_draft():
    from teoria.domains.goods.normalization.candidate_proposals import CandidateSelection, draft_from_candidates, propose_candidates
    from teoria_goods_normalization.candidates import CandidateBundle
    profile, ontology, corpus, bundle, group = candidate_case()
    # Repeated processing of the same original must not inflate document frequency.
    report = propose_candidates([bundle, CandidateBundle.model_validate_json(bundle.model_dump_json())], profile, ontology)
    proposed = next(g for g in report['groups'] if g['group_id'] == group.group_id)
    assert proposed['observation_count'] == proposed['document_count'] == 1
    assert proposed['decision'] == 'existing_concept_proposal'
    assert proposed['matches'][0]['concept_id'] == uid(2)
    assert proposed['observations'][0]['raw']['value_raw'] == '64'
    selection = CandidateSelection(group_id=group.group_id, concept_id=uid(2),
        units=[{'source_unit': 'GB', 'canonical_unit': 'GB'}])
    draft, proposal_checksum = draft_from_candidates([bundle], profile, ontology, [selection], version='test_2')
    assert draft.version == 'test_2' and profile.version == 'test_1'
    assert proposal_checksum == propose_candidates([bundle], profile, ontology)['checksum']
    result, _ = apply_profile(corpus, package(draft, ontology), run_id='candidate_test_2')
    assert result['attributes'][0]['status'] == 'applied'
    assert result['attributes'][0]['facts'][0]['value_raw'] == '64'
    assert result['attributes'][0]['facts'][0]['semantic_scope'] == 'per_component'


def test_candidate_groups_preserve_roles_scopes_units_and_source_conflicts():
    from teoria.domains.goods.normalization.candidate_proposals import propose_candidates
    from teoria_goods_normalization.candidates import CandidateBundle
    profile, ontology, corpus, bundle, _ = candidate_case()
    for a in corpus['documents'][0]['attributes']:
        if a['property_key'] == 'capacity':
            a['property_key'] = 'capacity_bytes'
    _, proposals = apply_profile(corpus, package(profile, ontology), run_id='different_contexts')
    grouped = CandidateBundle.model_validate(proposals['bundle'])
    requirements = [g for g in grouped.groups if g.context.kind == 'requirement']
    assert len(requirements) == 3
    assert {(g.context.role, g.context.scope, g.context.unit) for g in requirements} == {
        ('requirement_candidate', 'per_component', 'GB'),
        ('requirement_candidate', 'per_module', 'GB'),
        ('supported_capability', 'support_limit', 'TB')}
    changed = grouped.model_dump(mode='json')
    changed['groups'][0]['observations'][0]['raw']['value_raw'] = '999'
    changed['checksum'] = checksum({k: v for k, v in changed.items() if k != 'checksum'})
    with pytest.raises(ValueError, match='conflicting'):
        propose_candidates([grouped, CandidateBundle.model_validate(changed)], profile, ontology)
    with pytest.raises(ValueError, match='classification'):
        wrong = bundle.model_dump(mode='json'); wrong['classification_code'] = '4321150701'
        wrong['checksum'] = checksum({k: v for k, v in wrong.items() if k != 'checksum'})
        propose_candidates([CandidateBundle.model_validate(wrong)], profile, ontology)


@pytest.mark.parametrize('change', ['owner', 'unit', 'scope', 'grounding', 'overlap'])
def test_candidate_draft_rejects_unsafe_selections(change):
    from teoria.domains.goods.normalization.candidate_proposals import CandidateSelection, draft_from_candidates
    from teoria_goods_normalization.candidates import CandidateBundle
    profile, ontology, corpus, bundle, group = candidate_case()
    concept_id = uid(2)
    units = [{'source_unit': 'GB', 'canonical_unit': 'GB'}]
    if change == 'owner':
        concept_id = uid(4)
    if change == 'unit':
        units = [{'source_unit': 'GiB', 'canonical_unit': 'GB', 'multiplier': '1.073741824'}]
    if change in {'scope', 'grounding'}:
        a = corpus['documents'][0]['attributes'][0]
        if change == 'scope': a['semantic_scope'] = 'unknown'
        else: a['value_raw'] = '99999'
        _, proposals = apply_profile(corpus, package(profile, ontology), run_id='unsafe')
        bundle = CandidateBundle.model_validate(proposals['bundle'])
        group = next(g for g in bundle.groups if g.context.kind == 'requirement')
    if change == 'overlap':
        data = profile.model_dump(mode='json')
        data['requirements'][0]['source_property_keys'].append('capacity_bytes')
        profile = NormalizationProfile.model_validate(data)
    selection = CandidateSelection(group_id=group.group_id, concept_id=concept_id, units=units)
    with pytest.raises(ValueError):
        draft_from_candidates([bundle], profile, ontology, [selection], version='new_draft')


def test_relation_draft_requires_explicit_correct_direction_and_preserves_scope_kind():
    from teoria.domains.goods.normalization.candidate_proposals import CandidateSelection, draft_from_candidates
    from teoria_goods_normalization.candidates import CandidateBundle
    profile, ontology, corpus = example()
    corpus['documents'][0]['relations'][0]['kind'] = 'memory_belongs_to_server'
    _, proposals = apply_profile(corpus, package(profile, ontology), run_id='relation_candidate')
    bundle = CandidateBundle.model_validate(proposals['bundle'])
    group = next(g for g in bundle.groups if g.context.source_kind == 'memory_belongs_to_server')
    with pytest.raises(ValueError, match='direction'):
        draft_from_candidates([bundle], profile, ontology,
            [CandidateSelection(group_id=group.group_id, concept_id=uid(5))], version='new')
    draft, _ = draft_from_candidates([bundle], profile, ontology,
        [CandidateSelection(group_id=group.group_id, concept_id=uid(5), reverse=True)], version='new')
    assert draft.relations[-1].source_kind == 'memory_belongs_to_server'
    assert draft.relations[-1].reverse is True
    assert not any(r.source_kind == 'in_procurement_scope' for r in draft.relations)


def test_same_relation_label_can_map_to_distinct_published_endpoint_types():
    profile,ontology,corpus=example()
    ontology['relationships'].append({'concept_id':uid(6),'stable_key':'goods_test.has_server',
        'source_object_id':uid(101),'target_object_id':uid(102)})
    data=profile.model_dump(mode='json');data['ontology']['checksum']=checksum(ontology)
    data['relations'].append({'rule_id':'server_part','source_kind':'component_of',
        'relationship_concept_id':uid(6),'reverse':True})
    profile=NormalizationProfile.model_validate(data)
    corpus['documents'][0]['relations'].append({'id':'opposite','kind':'component_of',
        'source_id':'root','target_id':'m2','evidence':[{'node_id':'n'}]})
    # Same source label; endpoint types pick the correct relationship without ambiguity.
    normalized,_=apply_profile(corpus,package(profile,ontology),run_id='typed_relation')
    assert normalized['documents'][0]['relations'][0]['relationship_concept_id']==uid(5)
    assert normalized['documents'][0]['relations'][1]['relationship_concept_id']==uid(6)
    from teoria.domains.goods.normalization.candidate_proposals import _check_rule_overlap
    _check_rule_overlap(profile,ontology)
    data['relations'].append({'rule_id':'duplicate','source_kind':'component_of',
        'relationship_concept_id':uid(5),'reverse':True})
    with pytest.raises(ValueError,match='overlapping relation'):
        _check_rule_overlap(NormalizationProfile.model_validate(data),ontology)


async def test_standard_workflow_http_handoff_wait_resume_and_lost_response(tmp_path,monkeypatch):
    """Real contracts, HTTP routes and task bodies; model/DB lifecycle are controlled doubles."""
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.admin.auth import AdminAuthorizer
    from teoria.settings import Settings
    from teoria.domains.goods.normalization.admin_api import create_normalization_profile_router
    from teoria_pipelines.domains.public_procurement.specification_processing import standard_workflow as workflow
    from teoria_pipelines.domains.public_procurement.specification_processing.authoring_client import GoodsAuthoringClient
    profile,ontology,corpus=example()
    corpus['documents'][0]['attributes'][0]['property_key']='capacity_bytes'
    seed_data=profile.model_dump(mode='json');seed_data['entities'][0]['aliases']=['메모리']
    seed=NormalizationProfile.model_validate(seed_data)
    intermediate=profile
    final_data=profile.model_dump(mode='json');final_data['requirements'][0]['source_property_keys'].append('capacity_bytes')
    final_profile=NormalizationProfile.model_validate(final_data)
    packages={uid(200+i):compile_package(p,ontology,revision_id=UUID(int=200+i),approval_actor='principal:test')
        for i,p in enumerate([seed,intermediate,final_profile])}
    repo=AsyncMock();repo.export.side_effect=lambda revision_id:packages[str(revision_id)]
    approved=False;lost=False;operations={};generations=[];posts=[]
    class Operations:
        def __init__(self,repository):pass
        async def execute(self,operation_id,payload,*,actor):
            nonlocal lost
            assert actor=='principal:test'
            posts.append(operation_id)
            digest=checksum(payload)
            if operation_id not in operations:
                generations.append(operation_id)
                operations[operation_id]=digest
            assert operations[operation_id]==digest
            if operation_id.endswith('_entities'):
                if not approved:return {'operation_id':operation_id,'status':'awaiting_approval','ontology_draft_id':uid(800),'profile_revision_id':None}
                return {'operation_id':operation_id,'status':'approved','profile_revision_id':uid(201)}
            if not lost:
                lost=True
                raise RuntimeError('response lost after authoring commit')
            return {'operation_id':operation_id,'status':'approved','profile_revision_id':uid(202)}
    monkeypatch.setattr('teoria.domains.goods.normalization.semantic_operations.SemanticOperations',Operations)
    app=FastAPI();settings=Settings(admin_auth_mode='bearer',admin_api_token='test-token',admin_api_actor='principal:test',admin_api_roles='ontology_owner')
    app.include_router(create_normalization_profile_router(repo,AdminAuthorizer(settings)))
    monkeypatch.setattr(workflow,'GoodsAuthoringClient',lambda:GoodsAuthoringClient(base_url='http://authoring',token='test-token',transport=httpx.ASGITransport(app=app)))
    class Checkpoints:
        def __init__(self):self.state={};self.digest=None;self.status='failed';self.lease=None
        async def claim(self,key,digest):
            if self.digest is not None:assert self.digest==digest
            self.digest=digest
            if self.status=='completed':return deepcopy(self.state),None
            assert self.lease is None
            self.lease=UUID(int=900);self.status='running';return deepcopy(self.state),self.lease
        async def save(self,key,lease,state,*,status='running',error=None):
            assert lease==self.lease
            self.state=deepcopy(state);self.status=status
            if status!='running':self.lease=None
        async def renew(self,*args):pass
    checkpoints=Checkpoints()
    monkeypatch.setattr(workflow.StandardWorkflowRepository,'from_environment',lambda:checkpoints)
    for name in ['export_package','collect_candidates','author_candidates']:
        monkeypatch.setattr(workflow,name,getattr(workflow,name).fn)
    for name in ['stage_original_documents','parse_documents','extract_entity_relations','extract_requirements','resolve_attribute_semantics','persist_extraction','select_and_map_standard','persist_report']:
        monkeypatch.setattr(tasks,name,getattr(tasks,name).fn)
    monkeypatch.setattr(flows,'document_processing_flow',flows.document_processing_flow.fn)
    monkeypatch.setattr(flows,'start_execution',AsyncMock(return_value=None))
    monkeypatch.setattr(flows,'complete_execution',AsyncMock())
    monkeypatch.setattr(flows,'fail_execution',AsyncMock())
    source=tmp_path/'source.hwpx';source.write_bytes(b'controlled source')
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(corpus))
    manifest={'workflow_id':'integration_standard_workflow','base_profile_revision_id':uid(200),
        'extraction':{'run_id':'input','mode':'standard_management','model':'controlled_model','classification_code':'4321150102',
        'artifact_root':(tmp_path/'artifacts').as_uri(),
        'documents':[{'document_id':'doc','source_uri':source.as_uri(),'filename':source.name,'sha256':corpus['documents'][0]['source']['sha256']}],
        'extraction_checkpoint':{'uri':checkpoint.as_uri(),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()}}}
    result=await workflow.standard_workflow_flow.fn(manifest)
    assert result['status']=='awaiting_approval' and checkpoints.status=='awaiting_approval'
    approved=True
    with pytest.raises(RuntimeError,match='HTTP 503'):
        await workflow.standard_workflow_flow.fn(manifest)
    assert checkpoints.status=='failed'
    result=await workflow.standard_workflow_flow.fn(manifest)
    assert result['status']=='partial' # procurement-scope relation remains safely unresolved
    assert result['profile_revision_id']==uid(202)
    assert result['final_run']['summary']['applied']==4
    assert result['final_run']['summary']['reused_extraction'] is True
    assert len(generations)==2 # one authoring plan per phase despite waits and a lost response
    count=len(posts)
    replay=await workflow.standard_workflow_flow.fn(manifest)
    assert replay==result and len(posts)==count
    for artifact in result['final_run']['artifacts']:
        assert hashlib.sha256(Path(artifact['uri'].removeprefix('file://')).read_bytes()).hexdigest()==artifact['sha256']
