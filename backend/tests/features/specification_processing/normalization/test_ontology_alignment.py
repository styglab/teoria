"""Shadow semantic links preserve observations and require published, compatible concepts."""
from copy import deepcopy
import hashlib
import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum
from teoria.features.semantic_modeling.goods_dictionary.ontology_contracts import expression_snapshot
from teoria.features.specification_processing.models import OntologyAlignmentInput, SpecificationRun
from teoria.features.specification_processing.normalization.ontology_context import select_context, load_published_context
from teoria.features.specification_processing.normalization.ontology_alignment import propose_links


def example():
    pump, motor, prop, other, rel, version = [str(uuid4()) for _ in range(6)]
    content={'namespace':'goods_test','version':'1','objects':[
        {'business_object_id':'pump_revision','concept_id':pump,'stable_key':'goods_test.pump','name':'펌프',
         'description':'유체를 이송하는 장비. 구매 범위 묶음과 다르다.',
         'properties':[{'concept_id':prop,'stable_key':'goods_test.pump.power','name':'정격출력',
            'description':'펌프 자체의 정격 조건 출력.','value_type':'decimal','unit':'kW','allowed_units':['kW','W']}]},
        {'business_object_id':'motor_revision','concept_id':motor,'stable_key':'goods_test.motor','name':'전동기',
         'description':'전기 에너지를 회전 운동으로 바꾸는 장치.',
         'properties':[{'concept_id':other,'stable_key':'goods_test.motor.power','name':'전동기 출력',
            'description':'전동기 자체의 출력.','value_type':'decimal','unit':'kW','allowed_units':['kW']}]}],
        'relationships':[{'concept_id':rel,'stable_key':'goods_test.component_of','name':'구성품',
            'description':'전동기가 펌프의 구성에 포함된다.','source_object_id':'motor_revision','target_object_id':'pump_revision'}],
        'rules':[],'metrics':[]}
    ref={'version_id':version,'namespace':'goods_test','version':'1','checksum':dictionary_checksum(content)}
    snapshot=expression_snapshot([{'ontology':ref,'content':content}],[],[])
    corpus={'classification_code':None,'documents':[{'document_id':'d','source':{'sha256':'a'*64},
        'entities':[{'id':'e','name':'진공펌프','kind':'equipment','evidence':[{'node_id':'n1'}]},
                    {'id':'m','name':'전동기','kind':'equipment','evidence':[{'node_id':'n2'}]}],
        'attributes':[{'id':'p','subject_ids':['e'],'property_key':'power','property_raw':'정격출력',
            'data_type':'number','value_raw':'3','unit_raw':'kW','operator':'gte','operator_raw':'이상',
            'qualifiers_raw':[],'semantic_role':'requirement_candidate','semantic_scope':'per_item',
            'evidence':{'node_id':'n1'}}],
        'relations':[{'id':'r','source_id':'m','target_id':'e','kind':'component_of','evidence':[{'node_id':'n2'}]}],
        'parsed_document':{'nodes':[{'node_id':'n1','text':'진공펌프 정격출력 3kW 이상','kind':'paragraph','parent_id':None},
            {'node_id':'n2','text':'진공펌프에 전동기 포함','kind':'paragraph','parent_id':None}]}}], 'unavailable_documents':[]}
    ids={'e':pump,'m':motor,'p':prop,'other':other,'r':rel}
    return snapshot,corpus,ids


def authoring_api(snapshot):
    api = AsyncMock()
    api.ontology_publication.return_value = snapshot.ontologies[0]
    api.dictionary_meaning.return_value = snapshot.model_dump(mode='json')
    return api


def model(ids, mutate=None):
    async def generate(prompt,context,path,**kwargs):
        proposals=[]
        for row in context['observations']:
            observation=row['observation'];ev=observation['evidence']
            anchors=[e['node_id'] for e in ev] if isinstance(ev,list) else [ev['node_id']]
            proposals.append({'kind':row['kind'],'observation_id':observation['id'],
                'concept_id':ids[observation['id']],'evidence_node_ids':anchors,'rationale':'원문 대상과 게시 개념 정의를 대조한 검토 제안입니다.'})
        if mutate:mutate(proposals)
        return {'proposals':proposals}
    return AsyncMock(generate=AsyncMock(side_effect=generate))


async def test_shadow_links_preserve_all_raw_observations_and_do_not_claim_approval(tmp_path):
    snapshot,corpus,ids=example();before=deepcopy(corpus)
    result=await propose_links(corpus,snapshot,select_context(snapshot,ids.values()),None,model(ids),tmp_path)
    assert result['summary']['proposed']==result['summary']['observations']==4
    assert result['summary']['baseline_approved_links']==0
    assert result['mode']=='comparison_only' and not result['auto_applied'] and not result['accuracy_measured']
    assert result['observations_unchanged'] and corpus==before
    assert all(row['authority']=='suggestion' for row in result['observations'])


@pytest.mark.parametrize('bad',['wrong_owner','wrong_direction','unit','qualifier','unknown_role','invalid_scope','invalid_number','unknown_concept','duplicate','missing','evidence'])
async def test_invalid_predictions_are_held_and_original_observations_are_kept(tmp_path,bad):
    snapshot,corpus,ids=example();catalog=select_context(snapshot,ids.values());mutate=None;target='p'
    if bad=='wrong_owner':ids['p']=ids['other']
    elif bad=='wrong_direction':catalog[ids['r']]['source_concept_id'],catalog[ids['r']]['target_concept_id']=ids['e'],ids['m'];target='r'
    elif bad=='unit':
        corpus['documents'][0]['attributes'][0]['unit_raw']='kg'
        corpus['documents'][0]['parsed_document']['nodes'][0]['text']='진공펌프 정격출력 3kg 이상'
    elif bad=='qualifier':corpus['documents'][0]['attributes'][0]['qualifiers_raw']=['상시']
    elif bad=='unknown_role':corpus['documents'][0]['attributes'][0]['semantic_scope']='unknown'
    elif bad=='invalid_scope':corpus['documents'][0]['attributes'][0]['semantic_scope']='invented_scope'
    elif bad=='invalid_number':
        corpus['documents'][0]['attributes'][0]['value_raw']='높음'
        corpus['documents'][0]['parsed_document']['nodes'][0]['text']='진공펌프 정격출력 높음kW 이상'
    elif bad=='unknown_concept':ids['p']=str(uuid4())
    elif bad=='duplicate':mutate=lambda rows:rows.extend(deepcopy([r for r in rows if r['observation_id']=='p']))
    elif bad=='missing':mutate=lambda rows:rows.__setitem__(slice(None),[r for r in rows if r['observation_id']!='p'])
    elif bad=='evidence':
        def mutate(rows):
            for row in rows:
                if row['observation_id']=='p':row['evidence_node_ids']=['n2']
    before=deepcopy(corpus)
    result=await propose_links(corpus,snapshot,catalog,None,model(ids,mutate),tmp_path)
    row=next(r for r in result['observations'] if r['observation_id']==target)
    assert row['status']=='held' and row['reason']
    assert result['summary']['observations']==4 and corpus==before


async def test_missing_concept_remains_a_review_candidate_and_model_errors_keep_all_rows(tmp_path):
    snapshot,corpus,ids=example();catalog=select_context(snapshot,ids.values())
    unknown={**ids,'p':None}
    result=await propose_links(corpus,snapshot,catalog,None,model(unknown),tmp_path)
    row=next(r for r in result['observations'] if r['observation_id']=='p')
    assert row['status']=='unresolved' and row['ontology_review_candidate']
    failed=AsyncMock();failed.generate.side_effect=TimeoutError('private detail')
    result=await propose_links(corpus,snapshot,catalog,None,failed,tmp_path)
    assert len(result['observations'])==4 and all(r['status']=='held' for r in result['observations'])
    assert 'private detail' not in json.dumps(result)


async def test_existing_approved_link_is_not_overwritten_by_a_different_proposal(tmp_path):
    snapshot,corpus,ids=example();catalog=select_context(snapshot,ids.values())
    baseline={'documents':[{'document_id':'d','entities':[], 'attributes':[{'id':'p','meaning_status':'resolved',
        'ontology_concept_ref':ids['p'],'ontology':snapshot.ontologies[0]['ontology']}]}]}
    original=deepcopy(baseline);ids['p']=ids['other']
    result=await propose_links(corpus,snapshot,catalog,baseline,model(ids),tmp_path)
    row=next(r for r in result['observations'] if r['observation_id']=='p')
    assert row['reason']=='conflicts_with_approved_mapping' and row['baseline']['concept_id']==original['documents'][0]['attributes'][0]['ontology_concept_ref']
    assert baseline==original


async def test_published_context_checks_bytes_live_publication_and_expands_owner_ids(tmp_path):
    snapshot,_,ids=example();raw=snapshot.model_dump_json().encode();path=tmp_path/'context.json';path.write_bytes(raw)
    config=OntologyAlignmentInput(snapshot={'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()},concept_ids=[ids['p']])
    api=authoring_api(snapshot)
    _,catalog=await load_published_context(config,api)
    assert set(catalog)=={ids['p'],ids['e']}
    api.ontology_publication.return_value={**snapshot.ontologies[0], 'ontology': {**snapshot.ontologies[0]['ontology'], 'version_id':str(uuid4())}}
    with pytest.raises(ValueError,match='publication_unavailable'):await load_published_context(config,api)
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError,match='checksum_mismatch'):await load_published_context(config,api)


async def test_invalid_context_fails_before_registering_a_processing_run(tmp_path,monkeypatch):
    from teoria.features.specification_processing import flows
    from teoria.features.specification_processing import authoring_client
    path=tmp_path/'invalid.json';path.write_text('{}')
    request=SpecificationRun(run_id='invalid_context',mode='standard_management',artifact_root=tmp_path.as_uri(),
        documents=[{'document_id':'d','filename':'source.pdf','source_uri':'file:///source.pdf'}],
        ontology_alignment={'snapshot':{'uri':path.as_uri(),'sha256':'f'*64},'concept_ids':[str(uuid4())]})
    api=AsyncMock();api.__aenter__.return_value=api
    monkeypatch.setattr(authoring_client,'GoodsAuthoringClient',lambda:api)
    repository=AsyncMock();monkeypatch.setattr(flows.SpecificationRepository,'from_environment',lambda:repository)
    with pytest.raises(ValueError,match='checksum_mismatch'):await flows.start_execution.fn(request)
    repository.start.assert_not_awaited()


async def test_context_rejects_forged_publication_and_unverified_approved_expression(tmp_path):
    snapshot,_,ids=example();api=authoring_api(snapshot)
    async def check(candidate,reason):
        path=tmp_path/'context.json';raw=candidate.model_dump_json().encode();path.write_bytes(raw)
        config=OntologyAlignmentInput(snapshot={'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()},concept_ids=[ids['e']])
        with pytest.raises(ValueError,match=reason):await load_published_context(config,api)
    publication=deepcopy(snapshot.ontologies[0]);publication['content']['objects'][0]['description']='임의로 변경한 게시되지 않은 의미입니다.'
    publication['ontology']['checksum']=dictionary_checksum(publication['content'])
    await check(expression_snapshot([publication],[],[]),'publication_unavailable')
    source=str(uuid4())
    forged=expression_snapshot(snapshot.ontologies,[{'mapping_id':str(uuid4()),'source_entry_id':source,
        'ontology_version_id':snapshot.ontologies[0]['ontology']['version_id'],'target_concept_id':ids['e'],
        'owner_concept_id':None,'status':'approved','relation':'equivalent','scope_mode':'unclassified','classification_code':None}],
        [{'entry_id':source,'kind':'item_type','status':'approved','owner_entry_id':None,'preferred_name':'임의 표현'}])
    await check(forged,'dictionary_changed')


async def test_profile_and_context_cannot_mix_publication_versions(tmp_path):
    from teoria.features.goods_normalization.contracts import NormalizationProfile,NormalizationPackage,Concept,checksum
    snapshot,_,ids=example();path=tmp_path/'context.json';raw=snapshot.model_dump_json().encode();path.write_bytes(raw)
    config=OntologyAlignmentInput(snapshot={'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()},concept_ids=[ids['p']])
    profile=NormalizationProfile(profile_key='fixture',version='1',classification_code='1234567890',
        ontology={**snapshot.ontologies[0]['ontology'],'version_id':str(uuid4())},
        entities=[{'rule_id':'pump','concept_id':ids['e']}])
    body={'schema_version':2,'artifact_kind':'goods_normalization_package','profile_revision_id':str(uuid4()),
        'profile_checksum':checksum(profile),'profile':profile.model_dump(mode='json'),
        'concepts':[Concept(concept_id=ids['e'],stable_key='goods_test.pump',kind='object').model_dump(mode='json')],
        'approval_actor':'fixture:reviewer'}
    package=NormalizationPackage.model_validate({**body,'checksum':checksum(body)}).model_dump_json().encode()
    standard=tmp_path/'package.json';standard.write_bytes(package)
    from teoria.features.specification_processing.models import StandardReference
    reference=StandardReference(uri=standard.as_uri(),sha256=hashlib.sha256(package).hexdigest())
    api=authoring_api(snapshot)
    with pytest.raises(ValueError,match='profile_version_mismatch'):
        await load_published_context(config,api,standard=reference)


async def test_entity_context_includes_owned_specifications_outside_its_heading_section(tmp_path):
    snapshot,corpus,ids=example();document=corpus['documents'][0]
    document['entities'][0].update(document_roles=['procurement_scope','supply_target'],evidence=[{'node_id':'title'}])
    document['parsed_document']['nodes'].insert(0,{'node_id':'title','text':'진공펌프','kind':'heading','parent_id':None})
    document['parsed_document']['nodes'].insert(1,{'node_id':'section','text':'세부 규격','kind':'heading','parent_id':None})
    runner=model(ids)
    await propose_links(corpus,snapshot,select_context(snapshot,ids.values()),None,runner,tmp_path)
    request=runner.generate.await_args_list[0].args[1]
    assert 'n1' in {n['node_id'] for n in request['source_nodes']}
    assert request['observations'][0]['observation']['kind']=='equipment'
    assert request['observations'][0]['observation']['document_roles']==['procurement_scope','supply_target']


async def test_publication_references_need_no_dictionary_and_preserve_observations(tmp_path):
    from teoria.features.semantic_modeling.ontology.publication_contracts import PublishedOntologyContext
    snapshot, corpus, ids = example()
    api = authoring_api(snapshot)
    api.dictionary_meaning.side_effect = AssertionError('dictionary must not supply business definitions')
    config = OntologyAlignmentInput(publications=[snapshot.ontologies[0]['ontology']], concept_ids=[ids['p']])
    context, catalog = await load_published_context(config, api)
    assert isinstance(context, PublishedOntologyContext)
    assert set(catalog) == {ids['e'], ids['p']}
    api.dictionary_meaning.assert_not_awaited()
    before = deepcopy(corpus)
    runner = model(ids)
    report = await propose_links(corpus, context, catalog, None, runner, tmp_path)
    assert corpus == before and report['observations_unchanged']
    assert report['authority'] == 'suggestion' and not report['auto_applied']
    assert runner.generate.await_args_list[0].args[1]['approved_expression_examples'] == []
    # Reusing pinned definitions checks the Ontology owner again, without a dictionary.
    raw = context.model_dump_json().encode()
    path = tmp_path / 'publications.json'
    path.write_bytes(raw)
    pinned = OntologyAlignmentInput(snapshot={'uri':path.as_uri(), 'sha256':hashlib.sha256(raw).hexdigest()},
                                   concept_ids=[ids['p']])
    replay, replay_catalog = await load_published_context(pinned, api)
    assert replay == context and replay_catalog == catalog
    api.dictionary_meaning.assert_not_awaited()


async def test_publication_reference_identity_cannot_be_substituted():
    snapshot, _, ids = example()
    api = authoring_api(snapshot)
    config = OntologyAlignmentInput(publications=[{**snapshot.ontologies[0]['ontology'], 'checksum':'f'*64}],
                                    concept_ids=[ids['e']])
    with pytest.raises(ValueError, match='publication_unavailable'):
        await load_published_context(config, api)


async def test_pipeline_reads_publication_through_authenticated_http_without_dictionary_routes():
    import httpx
    from fastapi import FastAPI
    from unittest.mock import Mock
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.semantic_modeling.ontology.admin_router import create_ontology_authoring_router
    from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
    from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
    from teoria.settings import Settings
    snapshot, _, ids = example()
    service = Mock(spec=OntologyAuthoringService)
    service.publication.return_value = snapshot.ontologies[0]
    app = FastAPI()
    app.include_router(create_ontology_authoring_router(service, AdminAuthorizer(Settings(
        admin_auth_mode='bearer', admin_api_token='fixture-token',
        admin_api_actor='service:processing', admin_api_roles='ontology_owner'))))
    config = OntologyAlignmentInput(publications=[snapshot.ontologies[0]['ontology']], concept_ids=[ids['p']])
    async with GoodsAuthoringClient(base_url='http://isolated-authoring', token='fixture-token',
                                   transport=httpx.ASGITransport(app=app)) as api:
        context, catalog = await load_published_context(config, api)
    assert set(catalog) == {ids['e'], ids['p']}
    assert context.ontologies[0].content == snapshot.ontologies[0]['content']
    service.publication.assert_awaited_once_with(UUID(snapshot.ontologies[0]['ontology']['version_id']))


@pytest.mark.parametrize('inputs', [{}, {'snapshot':{'uri':'file:///context.json','sha256':'a'*64},
                                        'publications':'placeholder'}])
def test_alignment_has_one_explicit_definition_source(inputs):
    snapshot, _, ids = example()
    if inputs.get('publications'):
        inputs['publications'] = [snapshot.ontologies[0]['ontology']]
    with pytest.raises(ValueError, match='either publication'):
        OntologyAlignmentInput(concept_ids=[ids['e']], **inputs)
