"""Real SQL and authenticated HTTP for non-destructive Draft preparation."""
import asyncio
from copy import deepcopy
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
import httpx
import pytest

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.semantic_modeling.ontology.admin_router import create_ontology_authoring_router
from teoria.features.semantic_modeling.ontology.blueprint import OntologyBlueprint, apply_ontology_blueprint
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
from teoria.integrations.application_database import apply_migrations
from teoria.settings import Settings

DATABASE_URL = os.getenv('TEORIA_TEST_APP_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='isolated Application DB required')
ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope='module', autouse=True)
async def migrated():
    if DATABASE_URL:
        await apply_migrations(DATABASE_URL, ROOT / 'backend/migrations/application')


async def setup_case():
    namespace = 'draft_test_' + uuid4().hex
    common = {'code':'item','name':'Item','stable_key':namespace+'.item','description':'Observed subject',
              'identity_properties':['id'],'properties':[{'code':'id','name':'ID',
                  'stable_key':namespace+'.item.id','value_type':'string','cardinality':'one'}]}
    old = {'code':'local_definition','name':'Local definition','stable_key':namespace+'.local_definition',
           'description':'Replaced meta definition','identity_properties':['id'],
           'properties':[{'code':'id','name':'ID','stable_key':namespace+'.local_definition.id','value_type':'string'}]}
    source = OntologyBlueprint(schema_version='1.0',namespace=namespace,name='Synthetic',
        description='Isolated test',target_version='1.0.0',objects=[common,old])
    service = OntologyAuthoringService(DATABASE_URL)
    created = await apply_ontology_blueprint(service,source,actor='fixture:seed')
    source_id = UUID(created['ontology_version_id'])
    native = {'code':'memory','name':'Memory','stable_key':namespace+'.memory','description':'Native memory meaning',
              'properties':[{'code':'capacity','name':'Capacity','stable_key':namespace+'.memory.capacity',
                  'value_type':'decimal','unit':'GB','quantity_dimension':'information','allowed_units':['GB','TB']}]}
    blueprint = source.model_copy(update={'target_version':'2.0.0',
        'objects':[source.objects[0], source.objects[0].__class__.model_validate(native)]})
    app = FastAPI()
    app.include_router(create_ontology_authoring_router(service,AdminAuthorizer(Settings(
        admin_auth_mode='bearer',admin_api_token='fixture-token',admin_api_actor='fixture:authenticated-owner',
        admin_api_roles='ontology_owner'))))
    return service,source_id,blueprint,app


def client(app):
    return httpx.AsyncClient(base_url='http://isolated-authoring',transport=httpx.ASGITransport(app=app),
                            headers={'Authorization':'Bearer fixture-token'})


async def preview(c, source_id, blueprint):
    response = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-preview',
                            json={'blueprint':blueprint.model_dump(mode='json')})
    assert response.status_code == 200, response.text
    return response.json()


def request_body(blueprint, plan):
    return {'blueprint':blueprint.model_dump(mode='json'),'expected_plan_checksum':plan['plan_checksum'],
            'rationale':'Preserve the source and prepare a reviewed target Draft.'}


async def test_unpublished_source_is_preserved_with_stable_ids_and_authenticated_audit():
    service,source_id,blueprint,app = await setup_case()
    before = await service.get_version(source_id)
    async with client(app) as c:
        plan = await preview(c,source_id,blueprint)
        assert plan['ready'] and plan['source_status'] == 'draft'
        body = request_body(blueprint,plan)
        body['actor'] = 'untrusted:body'
        response = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts',json=body)
        assert response.status_code == 201, response.text
        result = response.json()
        replay = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts',json=body)
    assert replay.status_code == 201 and replay.json()['action'] == 'reused'
    assert replay.json()['ontology_version_id'] == result['ontology_version_id']
    assert await service.get_version(source_id) == before
    draft = await service.get_version(UUID(result['ontology_version_id']))
    assert draft['status'] == 'draft' and draft['based_on_version_id'] is None
    source_item = next(o for o in before['objects'] if o['code'] == 'item')
    copied_item = next(o for o in draft['objects'] if o['code'] == 'item')
    assert source_item['concept_id'] == copied_item['concept_id']
    assert source_item['business_object_id'] != copied_item['business_object_id']
    assert source_item['properties'][0]['concept_id'] == copied_item['properties'][0]['concept_id']
    audit = await service.audit(UUID(result['ontology_version_id']))
    assert audit[-1]['actor'] == 'fixture:authenticated-owner'
    assert audit[-1]['before_value']['blueprint']['target_version'] == '2.0.0'
    assert await service.published_artifact(source_id) is None
    assert await service.published_artifact(UUID(result['ontology_version_id'])) is None


async def test_stale_preview_is_rejected_and_insertion_failure_rolls_back(monkeypatch):
    service,source_id,blueprint,app = await setup_case()
    async with client(app) as c:
        plan = await preview(c,source_id,blueprint)
        item = (await service.get_version(source_id))['objects'][0]
        await service.update_item(source_id,kind='object',concept_id=UUID(item['concept_id']),
                                  changes={'description':'Concurrent edit'},actor='fixture:other')
        response = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts',
                                json=request_body(blueprint,plan))
        assert response.status_code == 409
        plan = await preview(c,source_id,blueprint)
        from unittest.mock import AsyncMock
        monkeypatch.setattr(service,'_validate',AsyncMock(return_value={'status':'invalid'}))
        response = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts',
                                json=request_body(blueprint,plan))
        assert response.status_code == 409
    assert len(await service.list_versions(blueprint.namespace)) == 1
    assert not any(row['stable_key'].endswith('.memory') for row in
                   await service.list_concepts(blueprint.namespace,published_only=False))
    async with service.repository.transaction() as conn:
        concepts,_ = await service.repository.blueprint_dependencies(conn,(await service.get_version(source_id))['ontology_id'])
        assert not any(row['stable_key'].endswith('.memory') for row in concepts)


async def test_concurrent_retries_create_only_one_target_and_edits_prevent_replay():
    service,source_id,blueprint,app = await setup_case()
    async with client(app) as c:
        plan = await preview(c,source_id,blueprint)
        path = f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts'
        responses = await asyncio.gather(*(c.post(path,json=request_body(blueprint,plan)) for _ in range(2)))
        assert [r.status_code for r in responses] == [201,201]
        assert {r.json()['action'] for r in responses} == {'created','reused'}
        identifier = UUID(responses[0].json()['ontology_version_id'])
        item = (await service.get_version(identifier))['objects'][0]
        await service.update_item(identifier,kind='object',concept_id=UUID(item['concept_id']),
                                  changes={'description':'Reviewed edit'},actor='fixture:other')
        assert (await c.post(path,json=request_body(blueprint,plan))).status_code == 409
    assert len(await service.list_versions(blueprint.namespace)) == 2


async def test_published_source_artifact_is_unchanged_and_remains_the_base():
    service,source_id,blueprint,app = await setup_case()
    await service.transition(source_id,action='submit',actor='fixture:owner')
    await service.transition(source_id,action='approve',actor='fixture:reviewer')
    await service.publish(source_id,actor='fixture:publisher')
    before = deepcopy(await service.published_artifact(source_id))
    async with client(app) as c:
        plan = await preview(c,source_id,blueprint)
        response = await c.post(f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts',
                                json=request_body(blueprint,plan))
        assert response.status_code == 201, response.text
    draft = await service.get_version(UUID(response.json()['ontology_version_id']))
    assert draft['based_on_version_id'] == str(source_id) and draft['status'] == 'draft'
    assert await service.published_artifact(source_id) == before


async def test_plan_rejects_historical_key_reuse_and_unauthenticated_apply():
    service,source_id,blueprint,app = await setup_case()
    item = await service.add_item(source_id,kind='object',payload={
        'code':'memory','name':'Different old meaning','stable_key':blueprint.namespace+'.memory'},actor='fixture:owner')
    await service.delete_item(source_id,kind='object',concept_id=UUID(item['concept_id']),actor='fixture:owner')
    async with client(app) as c:
        plan = await preview(c,source_id,blueprint)
        assert not plan['ready']
        assert any(row['code'] == 'historical_concept_requires_review' for row in plan['blockers'])
        path = f'/v1/admin/ontology-authoring/versions/{source_id}/blueprint-drafts'
        assert (await c.post(path,json=request_body(blueprint,plan))).status_code == 409
        c.headers.pop('Authorization')
        assert (await c.post(path,json=request_body(blueprint,plan))).status_code == 401
