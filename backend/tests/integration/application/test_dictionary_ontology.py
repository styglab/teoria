"""Opt-in SQL + authenticated HTTP: legacy proposals, publication, links and replay."""
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from teoria.integrations.application_database import apply_migrations
from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.settings import Settings
from teoria.platform.ontology.authoring.service import OntologyAuthoringService
from teoria.domains.goods.expression_links.registration_service import ExpressionRegistrationService
from teoria.domains.goods.expression_links.legacy.meaning_service import LegacyMeaningService
from teoria.domains.goods.expression_links.expression_link_service import ExpressionLinkService
from teoria.domains.goods.expression_links.admin_router import create_goods_dictionary_router
from teoria.domains.goods.expression_links.contracts import DictionarySubmission, source_literal_definition
from teoria.domains.goods.expression_links.snapshot_contracts import (
    ConceptDefinition, MeaningDecision, MeaningResolution, parse_dictionary_snapshot, resolve_snapshot,
)

URL = os.getenv('TEORIA_TEST_APP_DATABASE_URL')
pytestmark = pytest.mark.skipif(not URL, reason='isolated Application DB required')


async def test_real_dictionary_migrates_to_draft_and_only_published_links_apply():
    await apply_migrations(URL, Path('backend/migrations/application'))
    key='dictionary_test_'+uuid4().hex
    legacy=LegacyMeaningService(URL)
    decision=MeaningDecision(action='approve',rationale='합성 데이터의 정의와 원문 문맥을 확인했습니다.')
    item=ConceptDefinition(key=key,kind='item_type',preferred_name='검증 인버터',
        definition='직류 입력을 교류 출력으로 변환하는 합성 검증용 장치입니다.',references=['synthetic:test'])
    owner=await legacy.propose_concept(item,actor='fixture:owner')
    await legacy.decide('concept',owner['revision_id'],decision,actor='fixture:reviewer')
    prop=await legacy.propose_concept(ConceptDefinition(key=key+'_output',kind='characteristic',
        preferred_name='정격 출력',definition='정격 조건에서 출력하는 합성 검증용 전력입니다.',
        applicable_item_type_ids=[owner['concept_id']],value_kind='number',quantity_dimension='power',
        canonical_unit='W',allowed_units=['W','kW'],references=['synthetic:test']),actor='fixture:owner')
    ontology=OntologyAuthoringService(URL)
    draft=await ontology.create_ontology(namespace=key,name='검증 물품',description='Synthetic only',version='1',actor='fixture:owner')
    vid=UUID(draft['ontology_version_id'])
    dictionary=ExpressionRegistrationService(URL)
    service=ExpressionLinkService(URL,ontology_authoring=ontology)
    app=FastAPI()
    authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='fixture-token',
        admin_api_actor='fixture:authenticated',admin_api_roles='ontology_owner'))
    app.include_router(create_goods_dictionary_router(dictionary,authorizer,service))
    headers={'Authorization':'Bearer fixture-token'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test',headers=headers) as client:
        root='/v1/admin/goods/dictionary'
        assert (await client.post(root+'/concepts',json=item.model_dump(mode='json'))).status_code==409
        assert (await client.post(root+'/concept/'+str(owner['revision_id'])+'/decisions',json=decision.model_dump(mode='json'))).status_code==409
        changes={'baseline_checksum':'a'*64,'definitions':[],'mappings':[],'rationale':'별도 로컬 의미 작성을 허용하지 않는지 확인합니다.'}
        assert (await client.post(root+'/maintenance/fixture_attempt',json=changes)).status_code==409
        proposal={'ontology_draft_id':str(vid),'revision_ids':[str(prop['revision_id'])],
                  'rationale':'과거 정의와 단위 정책을 온톨로지 초안에서 검토합니다.'}
        assert (await client.post(root+'/ontology-draft-imports',json={**proposal,'actor':'fake'})).status_code==422
        imported=await client.post(root+'/ontology-draft-imports',json=proposal)
        assert imported.status_code==200, imported.text
        result=imported.json()
        assert result['published'] is False and result['expression_links_created'] is False
        assert len(result['items'])==2
        again=(await client.post(root+'/ontology-draft-imports',json=proposal)).json()
        assert again==result
        detail=await ontology.get_version(vid)
        assert detail['status']=='draft'
        obj=detail['objects'][0];attribute=obj['properties'][0]
        assert attribute['quantity_dimension']=='power' and attribute['allowed_units']==['W','kW']
        audit=await ontology.audit(vid)
        assert any(e['actor']=='fixture:authenticated' for e in audit)
        assert (await client.get(root+'/catalog?kind=concept&historical=true&query='+key)).json()['total']==2
        for action in ['submit','approve']:
            await ontology.transition(vid,action=action,actor='fixture:reviewer')
        published=await ontology.publish(vid,actor='fixture:publisher')
        ref={'version_id':str(vid),'namespace':key,'version':'1','checksum':published['artifact']['checksum']}
        text='검증 인버터 정격 출력 3 kW 이상'
        candidates=[]
        for candidate_key,kind,name in [('owner','item_type','검증 인버터'),('output','characteristic','정격 출력')]:
            candidates.append({'candidate_key':candidate_key,'kind':kind,'preferred_name':name,
                'definition':source_literal_definition(kind,name,'검증 인버터' if kind=='characteristic' else None),
                'owner_candidate_key':'owner' if kind=='characteristic' else None,
                'value_kind':'number' if kind=='characteristic' else None,'origin_ref':candidate_key,
                'evidence':[{'document_id':key,'source_sha256':'a'*64,'locator':'row1','quote':text}]})
        registered=await dictionary.author(key,DictionarySubmission(classification_code='1234567890',
            sources=[{'document_id':key,'source_sha256':'a'*64,'parser_version':'fixture','nodes':[{'locator':'row1','text':text}]}],
            candidates=candidates),actor='fixture:source')
        ids={d['candidate_key']:d['entry_id'] for d in registered['decisions']}
        for name,target,owner_id in [('output',attribute['concept_id'],obj['concept_id']),('owner',obj['concept_id'],None)]:
            body={'source_entry_id':ids[name],'ontology':ref,'target_concept_id':target,'owner_concept_id':owner_id,
                  'classification_code':'1234567890','scope_mode':'classified','relation':'equivalent',
                  'rationale':'원문 표현의 의미와 온톨로지 정의의 소유 대상을 대조했습니다.'}
            saved=await client.post(root+'/mappings',json=body)
            assert saved.status_code==200, saved.text
            mapping=saved.json()
            assert mapping['created_by']=='fixture:authenticated' and 'target_revision_id' not in mapping
            response=await client.post(root+'/mapping/'+mapping['mapping_id']+'/decisions',json=decision.model_dump(mode='json'))
            assert response.status_code==200, response.text
        request=MeaningResolution(source_entry_ids=[ids['output']],classification_code='1234567890')
        live=(await service.resolve(request))['items'][0]
        assert live['status']=='resolved' and live['concept_id']==attribute['concept_id']
        assert (await service.catalog('source',classification='1234567890',unresolved=True,query='검증 인버터'))['total']==0
        assert (await service.catalog('concept',classification='1234567890',query=key))['total']==2
        pinned=parse_dictionary_snapshot(await service.snapshot())
        next_draft=await ontology.create_draft(key,version='2',actor='fixture:owner',based_on_version_id=vid)
        next_id=UUID(next_draft['ontology_version_id'])
        cloned=await ontology.get_version(next_id)
        assert cloned['objects'][0]['properties'][0]['allowed_units']==['W','kW']
        for action in ['submit','approve']:
            await ontology.transition(next_id,action=action,actor='fixture:reviewer')
        await ontology.publish(next_id,actor='fixture:publisher')
        assert (await service.resolve(request))['items'][0]['status']=='unresolved'
        assert resolve_snapshot(pinned,request.source_entry_ids,request.classification_code)['items'][0]['status']=='resolved'
        assert any(r['requires_review'] for r in (await service.catalog('mapping'))['items'])
        assert (await client.post(root+'/ontology-draft-imports',json=proposal)).status_code==409
        # Dependency discovery reads each feature's public boundary against real SQL.
        from teoria.domains.goods.normalization.profiles.service import NormalizationProfileService
        from teoria.domains.goods.normalization.ontology_impact import GoodsOntologyImpactService
        from teoria.platform.ontology.bindings.repository import BindingRepository
        from teoria.platform.ontology.contracts.loader import RegistryCatalog
        profiles=NormalizationProfileService(URL,ontology_authoring=ontology)
        await profiles.create_from_template(next_id, {
            'profile_key':key, 'version':'1', 'classification_code':'1234567890',
            'entities':[{'rule_id':'inverter','concept_id':obj['stable_key']}],
            'requirements':[{'rule_id':'output','target_concept_id':obj['stable_key'],
                'property_concept_id':attribute['stable_key'],'roles':['requirement_candidate'],
                'scopes':['per_component'],'value_type':'number',
                'units':[{'source_unit':'W','canonical_unit':'W'}]}]}, actor='fixture:owner')
        review=await ontology.create_draft(key,version='3',actor='fixture:owner',based_on_version_id=next_id)
        review_id=UUID(review['ontology_version_id'])
        await ontology.update_item(review_id,kind='property',concept_id=UUID(attribute['concept_id']),
            changes={'unit':'kW'},actor='fixture:owner')
        report=await GoodsOntologyImpactService(ontology,profiles,service,BindingRepository(URL),
            RegistryCatalog(root=Path('.'),sources={},source_paths={},data_types={})).report(review_id)
        assert {'profile','expression_mapping'} <= {d['kind'] for d in report['dependencies']}
        assert attribute['concept_id'] in report['changed_concept_ids']
        assert all(d['existing_snapshot_preserved'] for d in report['dependencies'])
        assert (await ontology.get_version(next_id))['status']=='published'
