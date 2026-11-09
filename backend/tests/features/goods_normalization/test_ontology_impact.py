"""Draft changes expose dependent profiles, expression links and API mappings."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from backend.tests.integration.test_document_api_meanings import memory_case
from backend.tests.integration.test_goods_normalization_contract import uid
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.goods_normalization.ontology_impact import GoodsOntologyImpactService, dependency_impact
from teoria.features.semantic_modeling.ontology.admin_router import create_ontology_authoring_router
from teoria.settings import Settings


def test_property_constraints_and_owner_changes_are_compared_by_stable_concept():
    _, profile, before, _, _, _ = memory_case()
    after = deepcopy(before)
    after['objects'][0]['business_object_id'] = uid(999)
    for relation in after['relationships']:
        for field in ('source_object_id','target_object_id'):
            if relation[field]==before['objects'][0]['business_object_id']:
                relation[field]=uid(999)
    dependencies = [{'kind':'profile','id':'profile_a','concept_ids':[uid(2)],
                     'ontology':profile.ontology.model_dump(mode='json')}]
    assert dependency_impact(before, after, dependencies)['changed_concept_ids']==[]
    after['objects'][0]['properties'][0]['allowed_units']=['GB']
    report=dependency_impact(before,after,dependencies)
    assert report['changed_concept_ids']==[uid(2)]
    assert report['dependencies'][0]['reason']=='concept_changed'
    after['objects'][0]['properties'].pop(0)
    report=dependency_impact(before,after,dependencies)
    assert report['removed_concept_ids']==[uid(2)] and report['dependencies'][0]['reason']=='concept_removed'


async def test_review_http_reports_all_dependency_owners_without_mutating_them():
    catalog, profile, before, _, _, api_bindings = memory_case()
    after = deepcopy(before)
    before.update(ontology_version_id=uid(100),status='published')
    after.update(ontology_version_id=uid(800),status='draft',based_on_version_id=uid(100))
    after['objects'][0]['properties'][0]['unit']='TB'
    ontology=SimpleNamespace(
        get_version=AsyncMock(side_effect=lambda id:deepcopy(after if str(id)==uid(800) else before)),
        binding_impact=AsyncMock(return_value={'compatible':True,'incompatible_binding_count':0,'incompatible_bindings':[]}))
    profiles=SimpleNamespace(ontology_dependencies=AsyncMock(return_value=[{
        'kind':'profile','id':'profile_a','status':'approved','concept_ids':[uid(1),uid(2)],
        'ontology':profile.ontology.model_dump(mode='json')}]))
    expressions=SimpleNamespace(ontology_dependencies=AsyncMock(return_value=[{
        'kind':'expression_mapping','id':'expression_a','status':'approved','concept_ids':[uid(2)],
        'ontology':profile.ontology.model_dump(mode='json')}]))
    bindings=SimpleNamespace(list_bindings=AsyncMock(return_value=deepcopy(api_bindings)))
    service=GoodsOntologyImpactService(ontology,profiles,expressions,bindings,catalog)
    app=FastAPI()
    app.include_router(create_ontology_authoring_router(ontology,AdminAuthorizer(Settings()),dependency_reader=service.report))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as client:
        response=await client.get('/v1/admin/ontology-authoring/versions/'+uid(800)+'/binding-impact')
    assert response.status_code==200, response.text
    report=response.json()['dependency_impact']
    assert {d['kind'] for d in report['dependencies']}=={'profile','expression_mapping','api_mapping','semantic_binding'}
    assert report['review_required_count']==4 and report['changed_concept_ids']==[uid(2)]
    assert all(d['reason']=='concept_changed' and d['existing_snapshot_preserved'] for d in report['dependencies'])
    profiles.ontology_dependencies.assert_awaited_once_with('goods_test')
    expressions.ontology_dependencies.assert_awaited_once_with('goods_test')
    assert api_bindings[0]['status']=='approved'
