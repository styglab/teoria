import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.entrypoints.composition.workflow_catalog import workflow_catalog
from teoria.entrypoints.composition.workflow_management import prepare_workflow_run
from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.platform.workflow_management.admin_router import create_workflow_router
from teoria.settings import Settings


def test_generic_execution_uses_authenticated_actor_and_does_not_accept_extra_privileges():
    calls=[]
    def handler(request):
        body=json.loads(request.content or '{}');calls.append((request.url.path,body))
        if request.url.path.endswith('/deployments/filter'):
            return httpx.Response(200,json=[{'id':'deployment-id','name':'model-train'}])
        return httpx.Response(200,json={'id':'run-id','name':'training'})
    http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    catalog=workflow_catalog(True,semantic_enabled=False,formatid_enabled=False,legal_enabled=False)
    app=FastAPI();app.include_router(create_workflow_router(authorizer=AdminAuthorizer(Settings(admin_auth_mode='bearer',admin_api_token='synthetic',admin_api_actor='operator')),
        client=http,prefect_url='http://prefect/api',prefect_auth='test:synthetic',catalog=catalog,prepare_run=prepare_workflow_run(catalog)))
    execution={'image':'registry.example.com/models/test@sha256:'+'a'*64,'command':['python','train.py'],
        'model_name':'test','input_uri':'s3://datasets/v1/data.csv','input_sha256':'b'*64,'output_uri':'s3://models/run-1'}
    body={'idempotency_key':'12345678-1234-1234-1234-123456789012','execution':execution}
    path='/v1/admin/workflows/pipelines/model-train/runs'
    with TestClient(app) as api:
        assert api.post(path,json=body).status_code==401
        assert api.post(path,json={**body,'requested_by':'forged'},headers={'Authorization':'Bearer synthetic'}).status_code==422
        assert api.post(path,json={**body,'execution':{**execution,'volumes':['/var/run/docker.sock']}},headers={'Authorization':'Bearer synthetic'}).status_code==422
        response=api.post(path,json=body,headers={'Authorization':'Bearer synthetic'})
        assert response.status_code==202,response.text
    submitted=next(data for path,data in calls if path.endswith('/create_flow_run'))
    assert submitted['parameters']['requested_by']=='operator'
    assert submitted['parameters']['execution']['resources']['memory_mib']==1024
    assert submitted['parameters']['execution']['command']==['python','train.py']
    assert 'test:synthetic' not in str(submitted)
