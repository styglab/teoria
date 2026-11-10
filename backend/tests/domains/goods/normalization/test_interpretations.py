"""Review authority, immutable source observations and composition quantity semantics."""
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from backend.tests.domains.goods.normalization.meaning_proposals.test_meaning_review import example
from teoria.domains.goods.data_processing.storage.artifact_reader import verified_artifact
from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store
from teoria.domains.goods.normalization.application.meaning_application import (
    ApprovedInterpretation, InterpretationRequest, apply_interpretation,
)
from teoria.domains.goods.normalization.contracts import NormalizationProfile, checksum
from teoria.domains.goods.normalization.profiles.compiler import compile_package
from teoria.domains.goods.normalization.meaning_proposals.interpretation_service import InterpretationService
from teoria.domains.goods.normalization.meaning_proposals.interpretation_router import create_interpretation_router
from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.settings import Settings


def meaning_case():
    old, result, snapshot = example()
    content = deepcopy(snapshot.content)
    content.pop('ontology_version_id'); content.pop('status')
    content['relationships'] = []
    for obj in content['objects']:
        obj['business_object_id'] = str(uuid4())
    composition_id, quantity_id = uuid4(), uuid4()
    content['objects'].append({'business_object_id': str(uuid4()), 'concept_id': str(composition_id),
        'name': '구성 명세', 'stable_key': 'goods.composition_statement', 'properties': [{
            'concept_id': str(quantity_id), 'name': '구성 수량', 'stable_key': 'goods.composition_statement.quantity_value',
            'value_type': 'decimal', 'unit': None}]})
    for obj in content['objects']:
        for item in [obj, *obj['properties']]:
            item.setdefault('description', 'Synthetic meaning for isolated review tests')
    publication = {'ontology': dict(version_id=str(old.ontology.version_id), namespace=content['namespace'],
        version=content['version'], checksum=checksum(content)), 'content': content}
    profile = NormalizationProfile.model_validate({'profile_key': 'review_fixture', 'version': '1',
        'ontology': publication['ontology'], 'entities': [
            {'rule_id': 'entity_'+str(i), 'concept_id': str(p.concept_id)} for i,p in enumerate(old.entities)],
        'requirements': [dict(rule_id='property_'+str(i), target_concept_id=str(old.entities[1 if i==0 else 0].concept_id),
            property_concept_id=str(p.concept_id), roles=['supported_capability' if i==1 else 'requirement_candidate'],
            scopes=[p.semantic_scope], value_type='number', units=[
                {'source_unit': 'TB' if i==1 else 'GB' if i==0 else '개',
                 'canonical_unit': 'GB' if i in {0,1} else '개', 'multiplier': '1000' if i==1 else '1'}])
            for i,p in enumerate(old.properties)]})
    package = compile_package(profile, content, revision_id=uuid4(), approval_actor='fixture:profile-reviewer')
    document = result['extracted']['documents'][0]
    for e in document['entities']: e['kind'] = 'equipment'
    document['attributes'].append({'id': 'quantity', 'subject_ids': ['memory'], 'property_key': 'quantity',
        'property_raw': None, 'data_type': 'number', 'value_raw': '2', 'unit_raw': '개', 'operator': 'eq',
        'operator_raw': None, 'qualifiers_raw': [], 'semantic_role': 'requirement_candidate',
        'semantic_scope': 'system_total', 'evidence': {'node_id': 'spec'}})
    document['relations'] = [{'id': 'component', 'kind': 'component_of', 'source_id': 'memory',
        'target_id': 'root', 'basis': 'explicit', 'review_status': 'needs_review', 'evidence': [{'node_id': 'spec'}]}]
    request = InterpretationRequest.model_validate({'review_id': 'review_fixture', 'document_id': old.document_id,
        'source_sha256': old.source_sha256, 'result': old.result.model_dump(mode='json'),
        'profile_revision_id': str(package.profile_revision_id),
        'entities': [e.model_dump(mode='json') for e in old.entities],
        'properties': [p.model_dump(mode='json') for p in old.properties],
        'compositions': [{'relation_id': 'component', 'quantity_observation_id': 'quantity',
            'parent_id': 'root', 'child_id': 'memory', 'composition_concept_id': str(composition_id),
            'quantity_property_concept_id': str(quantity_id), 'relation_kind': 'physical_component',
            'inclusion_role': 'required', 'scope': '이 서버 구성에 공급할 모듈 수',
            'evidence': [{'document_id': 'd', 'node_id': 'spec', 'quote': 'DDR5 32GB RDIMM x 2개'}],
            'rationale': '공급 구성의 모듈 수량을 슬롯 수와 구분하는 명시적인 검토 제안이다.'}]})
    body = dict(artifact_kind='goods_approved_interpretation', status='approved', revision_id=str(uuid4()),
        approval_actor='fixture:reviewer', request=request.model_dump(mode='json'),
        package_checksum=package.checksum, ontology=publication['ontology'])
    approval = ApprovedInterpretation(**body, checksum=checksum(body))
    return request, result, package, publication, approval


def test_applied_interpretation_preserves_source_and_separates_quantity_from_capacity():
    _, result, package, publication, approval = meaning_case()
    before = deepcopy(result)
    applied = apply_interpretation(approval, result, package, publication, run_id='fixture')
    assert result == before and applied['source_observations_unchanged']
    rows = {o['source']['attribute_id']: o for o in applied['observations']}
    assert len(rows)==3 and rows['module']['value']['decimal']=='32'
    assert rows['limit']['scope']=='per_socket' and rows['limit']['source']['original_scope']=='support_limit'
    assert rows['count']['source']['original_subject_ids']==['slots']
    root = next(e['observation_id'] for e in applied['entities'] if e['source_entity_id']=='root')
    assert rows['count']['subject_refs']==[root]
    composition, = applied['compositions']
    assert composition['parent_ref']==root
    assert composition['quantity']['value']=='2' and composition['quantity']['unit_raw']=='개'
    assert composition['source_quantity_observation_id']=='quantity'
    assert all(o['value']['decimal']!='64' for o in applied['observations'])
    assert rows['count']['source']['approved_interpretation']['approval_actor']=='fixture:reviewer'


@pytest.mark.parametrize('change', ['quantity', 'relation', 'owner', 'quote', 'concept', 'classification', 'profile_scope', 'package'])
def test_wrong_context_or_ungrounded_interpretations_cannot_apply(change):
    request, result, package, publication, approval = meaning_case()
    if change=='quantity': result['extracted']['documents'][0]['attributes'][-1]['value_raw']='8'
    elif change=='relation': result['extracted']['documents'][0]['relations'][0]['target_id']='slots'
    elif change=='owner': result['extracted']['documents'][0]['attributes'][0]['subject_ids']=['unknown']
    elif change=='quote': request.compositions[0].evidence[0].quote='모듈 8개'
    elif change=='concept': request.compositions[0].quantity_property_concept_id=request.entities[0].concept_id
    elif change=='classification': result['extracted']['documents'][0]['classification_code']='4321150102'
    elif change=='profile_scope': request.properties[1].semantic_scope='system_total'
    else: approval.package_checksum='f'*64
    body=approval.model_dump(mode='json',exclude={'checksum'});body['request']=request.model_dump(mode='json')
    changed=ApprovedInterpretation(**body,checksum=checksum(body))
    with pytest.raises(ValueError): apply_interpretation(changed,result,package,publication,run_id='fixture')


class MemoryRepository:
    def __init__(self):
        self.rows={};self.events=[];self.lock=asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before=deepcopy((self.rows,self.events))
            try: yield self
            except BaseException:
                self.rows,self.events=before
                raise

    async def get(self, conn, revision_id, **kwargs): return self.rows[revision_id]

    async def insert(self, conn, request, reference, package, *, actor):
        row=next((r for r in self.rows.values() if r['review_id']==request.review_id),None)
        if row:
            if row['request_checksum']!=checksum(request) or row['created_by']!=actor: raise ValueError('conflict')
            return row
        row=dict(revision_id=uuid4(),review_id=request.review_id,request_ref=reference,request_checksum=checksum(request),
            profile_revision_id=package.profile_revision_id,ontology_version_id=package.profile.ontology.version_id,
            ontology_checksum=package.profile.ontology.checksum,package_checksum=package.checksum,
            status='draft',created_by=actor,approved_by=None)
        self.rows[row['revision_id']]=row
        return row

    async def set_status(self,conn,row,status,*,actor):
        row['status']=status
        if status=='approved': row['approved_by']=actor
        return row

    async def event(self,conn,row,action,actor,**kwargs):
        key=(row['revision_id'],action,kwargs.get('event_key',''))
        if not any(e['key']==key for e in self.events):self.events.append(dict(key=key,action=action,actor=actor,**kwargs))

    async def audit(self,conn,revision_id): return [e for e in self.events if e['key'][0]==revision_id]


async def service_case(tmp_path):
    request,result,package,publication,_=meaning_case()
    async with artifact_store(tmp_path.as_uri()) as store:
        ref=await store.put('result.json',json.dumps(result).encode())
    request.result.uri, request.result.sha256=ref.uri,ref.sha256
    reader=lambda reference: verified_artifact(reference,tmp_path,limit=20*1024*1024)
    profiles=AsyncMock(); profiles.repository.get.return_value=dict(status='approved',content_checksum=package.profile_checksum,
        package=package.model_dump(mode='json'))
    ontology=AsyncMock();ontology.published_artifact.return_value={'content':publication['content'],'status':'published'}
    repo=MemoryRepository()
    service=InterpretationService(repo,profiles,ontology,reader,lambda:artifact_store(tmp_path.as_uri()))
    return service,request,result,package,publication


async def approve(service,request):
    row=await service.create(request,actor='fixture:author'); revision=UUID(row['revision_id'])
    for action,status in [('submit','draft'),('approve','in_review')]:
        await service.transition(revision,action=action,expected_status=status,expected_request_checksum=checksum(request),
            actor='fixture:reviewer',comment='실제 출처와 의미를 대조한 검토 기록')
    return revision


async def test_approval_apply_and_deprecation_are_audited_and_source_remains_immutable(tmp_path):
    service,request,result,_,_=await service_case(tmp_path)
    row=await service.create(request,actor='fixture:author');revision=UUID(row['revision_id'])
    with pytest.raises(ValueError,match='approval_required'): await service.export(revision)
    with pytest.raises(ValueError,match='approval_required'):
        await service.apply(revision,run_id='fixture',actor='fixture:operator',expected_request_checksum=checksum(request))
    revision=await approve(service,request)
    approval=await service.export(revision)
    assert approval['approval_actor']=='fixture:reviewer'
    first=await service.apply(revision,run_id='fixture',actor='fixture:operator',expected_request_checksum=checksum(request))
    assert first==await service.apply(revision,run_id='fixture',actor='fixture:operator',expected_request_checksum=checksum(request))
    assert first['source_observations_unchanged']
    assert len([e for e in service.repository.events if e['action']=='apply'])==1
    await service.transition(revision,action='deprecate',expected_status='approved',
        expected_request_checksum=checksum(request),actor='fixture:reviewer')
    with pytest.raises(ValueError,match='approval_required'): await service.export(revision)
    assert json.loads((tmp_path/'result.json').read_text())==result


async def test_stale_review_changed_source_and_unpublished_ontology_block_transition(tmp_path):
    service,request,_,_,_=await service_case(tmp_path)
    row=await service.create(request,actor='fixture:author');revision=UUID(row['revision_id'])
    with pytest.raises(ValueError,match='changed_since_review'):
        await service.transition(revision,action='submit',expected_status='draft',expected_request_checksum='f'*64,actor='reviewer')
    await service.transition(revision,action='submit',expected_status='draft',expected_request_checksum=checksum(request),actor='reviewer')
    path=tmp_path/'result.json'; raw=path.read_bytes();path.write_bytes(raw+b' ')
    from teoria.domains.goods.data_processing.storage.artifact_reader import ArtifactReadError
    with pytest.raises(ArtifactReadError):
        await service.transition(revision,action='approve',expected_status='in_review',expected_request_checksum=checksum(request),actor='reviewer')
    path.write_bytes(raw);service.ontology_authoring.published_artifact.return_value=None
    with pytest.raises(ValueError,match='published_ontology'):
        await service.transition(revision,action='approve',expected_status='in_review',expected_request_checksum=checksum(request),actor='reviewer')
    assert service.repository.rows[revision]['status']=='in_review'
    assert not any(e['action']=='approve' for e in service.repository.events)


async def test_authenticated_principal_is_the_approval_actor_and_body_actor_is_rejected(tmp_path):
    service,request,_,_,_=await service_case(tmp_path)
    app=FastAPI();app.include_router(create_interpretation_router(service,AdminAuthorizer(Settings(
        admin_auth_mode='bearer',admin_api_token='fixture-token',admin_api_actor='user:reviewer'))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as client:
        path='/v1/admin/goods/interpretations'
        assert (await client.post(path,json=request.model_dump(mode='json'))).status_code==401
        client.headers['Authorization']='Bearer fixture-token'
        spoof=request.model_dump(mode='json');spoof['actor']='pretend-human'
        assert (await client.post(path,json=spoof)).status_code==422
        response=await client.post(path,json=request.model_dump(mode='json'))
        assert response.status_code==201,response.text
        revision=response.json()['revision_id']
        assert response.json()['created_by']=='user:reviewer'
        review=await client.get(path+'/'+revision+'/review')
        assert review.status_code==200 and review.json()['authority']=='suggestion'
        assert len(review.json()['source_observations']['attributes'])==4
        for action,status in [('submit','draft'),('approve','in_review')]:
            response=await client.post(path+'/'+revision+'/transitions',json=dict(action=action,expected_status=status,
                expected_request_checksum=checksum(request)))
            assert response.status_code==200,response.text
        response=await client.get(path+'/'+revision+'/approval')
        assert response.status_code==200 and response.json()['approval_actor']=='user:reviewer'
