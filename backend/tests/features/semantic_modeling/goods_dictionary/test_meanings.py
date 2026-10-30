from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    ConceptDefinition, MappingProposal, MeaningDecision, MeaningResolution,
)
from teoria.features.semantic_modeling.goods_dictionary.meaning_service import GoodsMeaningService
from teoria.features.specification_processing.normalization.dictionary_alignment import apply_concept_meanings


class Repository:
    def __init__(self):
        self.definitions=[];self.links=[];self.events=[];self.sources={}

    @asynccontextmanager
    async def transaction(self):
        before=deepcopy(self.__dict__)
        try:yield self
        except BaseException:
            self.__dict__.update(before)
            raise

    async def lock(self,c):pass
    async def concepts(self,c):return self.definitions
    async def concept(self,c,id):return next((r for r in self.definitions if str(r['revision_id'])==str(id)),None)
    async def mappings(self,c):return self.links
    async def mapping(self,c,id):return next((r for r in self.links if str(r['mapping_id'])==str(id)),None)
    async def by_id(self,c,id):return self.sources.get(str(id))
    async def source_evidence(self,c,id):return [{'document_id':'doc','locator':'/block/1','quote':'인버터 정격출력 3kW 이상'}]
    async def add_concept(self,c,id,revision,content,digest,actor):
        row=dict(revision_id=uuid4(),concept_id=id,concept_key=content['key'],revision=revision,
                 kind=content['kind'],content=content,content_checksum=digest,status='draft',created_by=actor)
        self.definitions.append(row);return deepcopy(row)
    async def add_mapping(self,c,proposal,evidence,actor):
        row={**proposal.model_dump(),'mapping_id':uuid4(),'status':'draft','evidence':evidence,'created_by':actor}
        self.links.append(row);return deepcopy(row)
    async def set_status(self,c,kind,id,status):
        row=await (self.concept(c,id) if kind=='concept' else self.mapping(c,id));row['status']=status
    async def meaning_event(self,c,kind,id,action,actor,reason):self.events.append((kind,id,action,actor,reason))


def item(key='inverter'):
    return ConceptDefinition(key=key,kind='item_type',preferred_name='인버터',
        definition='직류 전력을 교류 전력으로 변환하는 전력 변환 장치.',references=['design:inverter'])


def decision(action='approve'):
    return MeaningDecision(action=action,rationale='명시한 정의와 적용 범위를 확인한 정책 판정')


async def approved(service, definition):
    row=await service.propose_concept(definition,actor='policy:test')
    return await service.decide('concept',row['revision_id'],decision(),actor='policy:test')


async def link(service, source, target, **kw):
    row=await service.propose_mapping(MappingProposal(source_entry_id=source,target_revision_id=target['revision_id'],
        rationale='원문의 대상과 정의 및 적용 범위를 함께 대조함',**kw),actor='policy:test')
    return await service.decide('mapping',row['mapping_id'],decision(),actor='policy:test')


async def test_only_approved_mapping_resolves_and_revised_definition_invalidates_old_mapping():
    repo=Repository();service=GoodsMeaningService(repository=repo);source=uuid4()
    repo.sources[str(source)]={'kind':'item_type'}
    target=await approved(service,item())
    request=MeaningResolution(source_entry_ids=[source])
    assert (await service.resolve(request))['items'][0]['status']=='unresolved'
    mapping=await link(service,source,target)
    result=(await service.resolve(request))['items'][0]
    assert result['concept_id']==str(target['concept_id']) and result['mapping_ids']==[str(mapping['mapping_id'])]
    revision=await approved(service,item().model_copy(update={'definition':'직류 입력을 교류 출력으로 변환하는 장치이며 정류기는 제외한다.'}))
    assert revision['revision']==2 and revision['concept_id']==target['concept_id']
    assert (await service.resolve(request))['items'][0]['status']=='unresolved'
    assert any(e[2]=='superseded' for e in repo.events)
    assert {e[3] for e in repo.events}=={'policy:test'}


async def test_scope_conflicts_and_related_mappings_never_auto_equate():
    repo=Repository();service=GoodsMeaningService(repository=repo);source=uuid4();repo.sources[str(source)]={'kind':'item_type'}
    a=await approved(service,item());b=await approved(service,item('other'))
    await link(service,source,a,classification_code='1234567890')
    assert (await service.resolve(MeaningResolution(source_entry_ids=[source])))['items'][0]['status']=='unresolved'
    await link(service,source,b,classification_code='1234567890',relation='related')
    request=MeaningResolution(source_entry_ids=[source],classification_code='1234567890')
    assert (await service.resolve(request))['items'][0]['status']=='resolved'
    await link(service,source,b,classification_code='1234567890')
    assert (await service.resolve(request))['items'][0]['reason']=='ambiguous_approved_mappings'


async def test_characteristic_requires_resolved_owner_and_deprecated_owner_blocks_reuse():
    repo=Repository();service=GoodsMeaningService(repository=repo);source=uuid4();attr=uuid4()
    repo.sources[str(source)]={'kind':'item_type'}
    repo.sources[str(attr)]={'kind':'characteristic','owner_entry_id':source}
    owner=await approved(service,item())
    characteristic=ConceptDefinition(key='rated_output_power',kind='characteristic',preferred_name='정격출력',
        definition='명시한 정격 운전 조건에서 장치가 출력할 수 있는 전력.',value_kind='number',
        applicable_item_type_ids=[owner['concept_id']],quantity_dimension='power',canonical_unit='W',
        allowed_units=['W','kW'],references=['design:rated_output_power'])
    target=await approved(service,characteristic)
    await link(service,attr,target,owner_concept_id=owner['concept_id'])
    request=MeaningResolution(source_entry_ids=[attr])
    assert (await service.resolve(request))['items'][0]['status']=='unresolved'
    await link(service,source,owner)
    assert (await service.resolve(request))['items'][0]['status']=='resolved'
    await service.decide('concept',owner['revision_id'],decision('deprecate'),actor='policy:test')
    assert (await service.resolve(request))['items'][0]['status']=='unresolved'


async def test_rejected_definitions_cannot_be_approved_and_drafts_are_immutable():
    repo=Repository();service=GoodsMeaningService(repository=repo)
    draft=await service.propose_concept(item(),actor='test')
    same=await service.propose_concept(item(),actor='test')
    assert same['revision_id']==draft['revision_id']
    await service.decide('concept',draft['revision_id'],decision('reject'),actor='test')
    with pytest.raises(ValueError,match='lifecycle'):
        await service.decide('concept',draft['revision_id'],decision(),actor='test')


def test_unit_policy_cannot_omit_dimension_or_canonical_unit():
    with pytest.raises(ValidationError):
        ConceptDefinition(key='bad',kind='characteristic',preferred_name='출력',definition='이 정의는 검증용 충분한 길이이다.',
            applicable_item_type_ids=[uuid4()],value_kind='number',allowed_units=['W'],references=['test'])


def test_application_preserves_source_and_does_not_convert_or_publish_ontology_ids():
    sid=str(uuid4());cid=str(uuid4())
    documents=[{'entities':[],'attributes':[{'source_term_ref':'source_term:'+sid,'value_raw':'3','unit_raw':'kW'}]}]
    before=deepcopy(documents)
    resolution={'policy_version':'test','items':[{'source_entry_id':sid,'status':'resolved','reason':'approved',
        'concept_id':cid,'revision_id':str(uuid4()),'mapping_ids':[str(uuid4())],
        'definition':{'allowed_units':['W','kW'],'value_kind':'number'}}]}
    applied=apply_concept_meanings(documents,resolution)['documents'][0]['attributes'][0]
    assert documents==before and applied['typed_value']=={'decimal':'3','unit':'kW'}
    assert applied['dictionary_concept_ref']=='dictionary_concept:'+cid and 'characteristic_ref' not in applied
    documents[0]['attributes'][0]['unit_raw']='kg'
    invalid=apply_concept_meanings(documents,resolution)['documents'][0]['attributes'][0]
    assert invalid['value_validation']=='unit_not_allowed' and 'typed_value' not in invalid


def test_meaning_http_uses_authenticated_actor_and_rejects_body_actor():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.semantic_modeling.goods_dictionary.admin_router import create_goods_dictionary_router
    from teoria.settings import Settings
    repo=Repository();service=GoodsMeaningService(repository=repo)
    authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='fixture-token',
        admin_api_actor='system:authenticated',admin_api_roles='ontology_owner'))
    app=FastAPI();app.include_router(create_goods_dictionary_router(None,authorizer,service))
    with TestClient(app) as client:
        path='/v1/admin/goods/dictionary/concepts';headers={'Authorization':'Bearer fixture-token'}
        assert client.post(path,json=item().model_dump(mode='json')).status_code==401
        assert client.post(path,headers=headers,json={**item().model_dump(mode='json'),'actor':'fake'}).status_code==422
        response=client.post(path,headers=headers,json=item().model_dump(mode='json'))
        assert response.status_code==200 and response.json()['created_by']=='system:authenticated'
        revision=response.json()['revision_id']
        result=client.post('/v1/admin/goods/dictionary/concept/'+revision+'/decisions',headers=headers,
                          json=decision().model_dump(mode='json'))
        assert result.status_code==200 and result.json()['status']=='approved'
        assert all(e[3]=='system:authenticated' for e in repo.events)


def test_missing_classification_has_a_separate_scope_and_pinned_legacy_semantics_survive():
    from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import scope_matches
    old_mapping={'classification_code':None}
    assert scope_matches(old_mapping,None)
    assert not scope_matches(old_mapping,'4321150102')
    assert scope_matches(old_mapping,'4321150102',legacy=True)
    assert not scope_matches({**old_mapping,'scope_mode':'unclassified'},'4321150102',legacy=True)
    assert scope_matches({**old_mapping,'scope_mode':'independent'},'4321150102')
    classified={'classification_code':'4321150102','scope_mode':'classified'}
    assert scope_matches(classified,'4321150102')
    assert not scope_matches(classified,None)
    assert not scope_matches(classified,'4321150701')
