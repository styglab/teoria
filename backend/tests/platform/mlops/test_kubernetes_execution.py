import json

import httpx
import pytest

from teoria.integrations.model_execution.kubernetes import KubernetesExecutor
from teoria.integrations.model_execution.settings import ExecutionSettings
from teoria.platform.mlops.contracts import ServingRequest, TrainingRequest

IMAGE='registry.example.com/models/test@sha256:'+'a'*64
LABELS={'app.kubernetes.io/managed-by':'teoria-mlops'}


def policy(monkeypatch,tmp_path):
    token=tmp_path/'token';token.write_text('synthetic-service-account')
    monkeypatch.setenv('TEORIA_MODEL_KUBERNETES_TOKEN_FILE',str(token))
    monkeypatch.setenv('TEORIA_MODEL_ALLOWED_REGISTRIES','registry.example.com')
    return ExecutionSettings.from_environment()


def serving(**changes):
    return ServingRequest.model_validate({**dict(image=IMAGE,command=['python','serve.py'],deployment_id='test',model_name='test',model_version=2,model_sha256='b'*64),**changes})


async def test_rollout_waits_for_old_replicas_to_be_removed(monkeypatch,tmp_path):
    reads=[];calls=[]
    def handler(request):
        assert request.headers['Authorization']=='Bearer synthetic-service-account'
        calls.append((request.method,request.url.path))
        if request.method=='GET' and '/deployments/' in request.url.path:
            reads.append(True)
            if len(reads)<=2:return httpx.Response(404)
            status={'observedGeneration':2,'updatedReplicas':1,'availableReplicas':1,'replicas':2 if len(reads)==3 else 1}
            return httpx.Response(200,json={'metadata':{'generation':2,'labels':LABELS},'status':status})
        if request.method=='GET':return httpx.Response(404)
        return httpx.Response(200,json={'metadata':{'generation':2,'labels':LABELS}})
    async with httpx.AsyncClient(base_url='https://cluster',transport=httpx.MockTransport(handler)) as http:
        runtime=KubernetesExecutor(policy(monkeypatch,tmp_path),http=http)
        result=await runtime.deploy(serving(),'run-1')
    assert len(reads)==4
    assert result['endpoint']=='http://model-serving-test.teoria-models.svc:8080'
    assert not any(method=='DELETE' for method,_ in calls)


async def test_failed_rollout_restores_previous_specification(monkeypatch,tmp_path):
    previous={'metadata':{'labels':LABELS,'generation':1},'spec':{'replicas':1,'template':{'spec':{'containers':[{'name':'model','image':'previous-image'}]}}}}
    patches=[]
    def handler(request):
        if request.method=='GET':return httpx.Response(200,json=previous)
        if request.method=='PATCH':patches.append((request.url.path,json.loads(request.content)))
        return httpx.Response(200,json={'metadata':{'generation':2}})
    async with httpx.AsyncClient(base_url='https://cluster',transport=httpx.MockTransport(handler)) as http:
        runtime=KubernetesExecutor(policy(monkeypatch,tmp_path),http=http)
        with pytest.raises(TimeoutError):
            await runtime.deploy(serving(readiness_timeout_seconds=1),'run-2')
    assert patches[-1][1]=={'spec':previous['spec']}


async def test_unmanaged_job_is_never_deleted_on_rejection(monkeypatch,tmp_path):
    calls=[]
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200,json={'metadata':{'labels':{'app':'other-application'}}})
    spec=TrainingRequest(image=IMAGE,command=['python','train.py'],model_name='test',input_uri='s3://data/train.csv',input_sha256='b'*64,output_uri='s3://models/run')
    async with httpx.AsyncClient(base_url='https://cluster',transport=httpx.MockTransport(handler)) as http:
        runtime=KubernetesExecutor(policy(monkeypatch,tmp_path),http=http)
        with pytest.raises(ValueError,match='not owned'):
            await runtime.train(spec,'run-3')
    assert calls==['GET']
