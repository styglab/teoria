"""Opt-in real external-image training, serving replacement and failed-candidate recovery."""
import asyncio
import io
import json
import os
from pathlib import Path
import tarfile
import time
import uuid

import httpx
import pytest

from teoria.integrations.model_execution.docker import DockerExecutor
from teoria.integrations.model_execution.settings import ExecutionSettings
from teoria.platform.mlops.contracts import TrainingRequest, ServingRequest

pytestmark = pytest.mark.skipif(os.getenv('TEORIA_TEST_MODEL_EXECUTION_DOCKER') != '1', reason='explicit Docker model execution test')


async def test_external_image_training_serving_update_and_rollback(monkeypatch):
    docker = pytest.importorskip('docker')
    client = docker.from_env()
    project = 'model-test-' + uuid.uuid4().hex[:10]
    network = client.networks.create(project + '_default')
    registry = None
    runtime = None
    image = None
    try:
        registry = client.containers.run('registry:3.1.2', detach=True, ports={'5000/tcp':('127.0.0.1',None)}, environment={'OTEL_TRACES_EXPORTER':'none'})
        registry.reload()
        port = registry.attrs['NetworkSettings']['Ports']['5000/tcp'][0]['HostPort']
        host = '127.0.0.1:' + port
        for _ in range(60):
            if registry.exec_run(['wget','--quiet','--spider','http://127.0.0.1:5000/v2/']).exit_code == 0:
                break
            await asyncio.sleep(.2)
        else:
            pytest.fail('test registry did not start')
        # The image is a standalone Python application, with no Teoria or Prefect imports.
        source = r'''
import json,os,sys,time
from http.server import HTTPServer,BaseHTTPRequestHandler
if sys.argv[1]=='train':
    assert os.environ['TEORIA_INPUT_URI'].startswith('s3://')
    assert json.loads(os.environ['TEORIA_TRAINING_PARAMETERS'])['trees']==10
    assert not os.environ.get('PREFECT_API_AUTH_STRING')
    assert not os.path.exists('/var/run/docker.sock')
    sys.exit(0)
if sys.argv[1]=='slow': time.sleep(60)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'version':os.getenv('TEORIA_MODEL_VERSION')}).encode())
    def do_POST(self): self.do_GET()
    def log_message(self,*args): pass
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
'''
        context = io.BytesIO()
        with tarfile.open(fileobj=context, mode='w') as archive:
            base = os.getenv('TEORIA_MODEL_TEST_BASE_IMAGE','teoria-platform-admin:latest')
            for name, data in {'Dockerfile':f'FROM {base}\nCOPY job.py /tmp/job.py\n', 'job.py':source}.items():
                encoded=data.encode();info=tarfile.TarInfo(name);info.size=len(encoded);archive.addfile(info,io.BytesIO(encoded))
        context.seek(0)
        tag = host + '/models/smoke:v1'
        image,_ = await asyncio.to_thread(client.images.build, fileobj=context, custom_context=True, tag=tag, rm=True, pull=False, network_mode='none')
        for event in client.images.push(tag,stream=True,decode=True):
            assert 'error' not in event, event
        image.reload()
        digest = next(d for d in image.attrs['RepoDigests'] if d.startswith(host + '/models/smoke@'))
        monkeypatch.setenv('TEORIA_MODEL_ALLOWED_REGISTRIES',host)
        monkeypatch.setenv('TEORIA_COMPOSE_PROJECT_NAME',project)
        monkeypatch.setenv('TEORIA_MODEL_DOCKER_NETWORK',network.name)
        settings = ExecutionSettings.from_environment()
        # Probe on the actual Docker network even when the daemon is remote.
        helper = client.containers.run(os.getenv('TEORIA_MODEL_TEST_BASE_IMAGE','teoria-platform-admin:latest'),
            ['python','-c','import time;time.sleep(600)'], detach=True, network=network.name,
            labels={'io.teoria.project':project})
        async def container_transport(request):
            code = "import sys,urllib.request; r=urllib.request.urlopen(sys.argv[1],timeout=2); print(r.status); sys.stdout.write(r.read().decode())"
            result = await asyncio.to_thread(helper.exec_run, ['python','-c',code,str(request.url)])
            if result.exit_code:
                raise httpx.ConnectError('serving is unavailable', request=request)
            status,body=result.output.decode().split('\n',1)
            return httpx.Response(int(status),content=body)
        http=httpx.AsyncClient(transport=httpx.MockTransport(container_transport))
        runtime=DockerExecutor(settings,client=client,http=http)
        trained=await runtime.train(TrainingRequest(image=digest,command=['python','/tmp/job.py','train'],model_name='test',
            input_uri='s3://data/v1/train.csv',input_sha256='a'*64,output_uri='s3://models/test/run-1',parameters={'trees':10},timeout_seconds=10), 'training-1')
        assert trained['exit_code']==0
        assert not client.containers.list(all=True,filters={'label':['io.teoria.project='+project,'io.teoria.role=model-training']})
        serving=dict(image=digest,command=['python','/tmp/job.py','serve'],deployment_id='test',model_name='test',model_version=1,model_sha256='b'*64,readiness_timeout_seconds=10)
        first=await runtime.deploy(ServingRequest(**serving),'deploy-1')
        assert first['endpoint']=='http://' + project + '-model-serving-test:8080'
        failed={**serving,'command':['python','-c','import sys;sys.exit(1)'],'model_version':2,'readiness_timeout_seconds':1}
        with pytest.raises(TimeoutError):
            await runtime.deploy(ServingRequest(**failed),'deploy-failed')
        assert (await http.get(first['endpoint']+'/health')).json()['version']=='1'
        await runtime.deploy(ServingRequest(**{**serving,'model_version':2}), 'deploy-2')
        assert (await http.get(first['endpoint']+'/health')).json()['version']=='2'
        await runtime.stop('test')
        assert not client.containers.list(all=True,filters={'label':['io.teoria.project='+project,'io.teoria.role=model-serving']})
        await http.aclose()
    finally:
        for c in client.containers.list(all=True,filters={'label':'io.teoria.project='+project}):
            c.remove(force=True)
        if registry is not None: registry.remove(force=True,v=True)
        network.remove()
        if image is not None:
            try: client.images.remove(image.id,force=True)
            except docker.errors.APIError: pass
        client.close()
