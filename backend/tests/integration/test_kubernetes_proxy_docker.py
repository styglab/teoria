"""Opt-in verification of the generic overlay's nginx routing and MLflow authentication."""
import io
import os
from pathlib import Path
import tarfile
import time
import uuid

import pytest

pytestmark=pytest.mark.skipif(os.getenv('TEORIA_TEST_KUBERNETES_PROXY_DOCKER')!='1',reason='explicit Kubernetes web proxy test')


def test_portable_ui_proxy_routes_apis_and_protects_mlflow():
    docker=pytest.importorskip('docker');client=docker.from_env()
    root=Path(__file__).resolve().parents[3]
    name='teoria-proxy-check-'+uuid.uuid4().hex[:10]
    network=client.networks.create(name)
    containers=[]
    try:
        code=r'''
import json,threading,time
from http.server import HTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/api/admin/version' and self.headers.get('Authorization')!='Basic dGVzdDpzeW50aGV0aWM=':
            self.send_response(401);self.end_headers();return
        self.send_response(200);self.end_headers()
        self.wfile.write(json.dumps({'path':self.path,'authorization':self.headers.get('Authorization','')}).encode())
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')));self.do_GET()
    def log_message(self,*args):pass
for port in (8000,8001,4200,5000):
    threading.Thread(target=HTTPServer(('0.0.0.0',port),Handler).serve_forever,daemon=True).start()
time.sleep(300)
'''
        base=os.getenv('TEORIA_KUBERNETES_PROXY_CLIENT_IMAGE','teoria-platform-admin:mlops-validation')
        backend=client.containers.run(base,['python','-c',code],network=network.name,detach=True)
        containers.append(backend)
        network.disconnect(backend);network.connect(backend,aliases=[service+'.teoria.svc.cluster.local' for service in ('admin-api','runtime-api','prefect-server','mlflow')])
        proxy=client.containers.create('nginx:1.27-alpine',entrypoint=['/bin/sh','/etc/teoria_proxy/start.sh'],network=network.name,name=name)
        containers.append(proxy)
        content=io.BytesIO()
        with tarfile.open(fileobj=content,mode='w') as archive:
            for filename in ('default.conf.template','start.sh'):
                archive.add(root/'deploy/kubernetes/components/web_proxy'/filename,arcname='teoria_proxy/'+filename)
        content.seek(0);proxy.put_archive('/etc',content.read());proxy.start()
        deadline=time.monotonic()+20
        while proxy.exec_run(['wget','--quiet','--spider','http://127.0.0.1/health']).exit_code:
            assert time.monotonic()<deadline,'portable proxy startup failed'
            time.sleep(.2)
        helper=client.containers.run(base,['python','-c','import time;time.sleep(300)'],detach=True,network=network.name)
        containers.append(helper)
        assertions=r'''
import httpx,sys
base='http://'+sys.argv[1]
with httpx.Client(trust_env=False) as client:
    for path,expected in [('/admin-api/v1/admin/test?q=1','/v1/admin/test?q=1'),('/runtime-api/v1/version','/v1/version'),('/prefect/api/health','/api/health'),('/prefect/','/prefect/')]:
        result=client.get(base+path,headers={'Authorization':'Bearer synthetic-admin-token'})
        assert result.status_code==200,(path,result.status_code)
        assert result.json()['path']==expected,(path,result.text)
        assert result.json()['authorization']=='Bearer synthetic-admin-token'
    assert client.get(base+'/mlflow/health').status_code==401
    assert client.get(base+'/mlflow/health',auth=('test','incorrect')).status_code==401
    result=client.get(base+'/mlflow/health',auth=('test','synthetic'))
    assert result.status_code==200
    assert result.json()['path']=='/mlflow/health'
    assert result.json()['authorization']==''
    result=client.post(base+'/admin-api/v1/admin/upload',content=b'example',headers={'Authorization':'Bearer synthetic-admin-token'})
    assert result.json()['path']=='/v1/admin/upload'
    print('Portable proxy path rewriting, authorization forwarding and MLflow access control verified')
'''
        result=helper.exec_run(['python','-c',assertions,name])
        assert result.exit_code==0,result.output.decode()
    finally:
        for container in reversed(containers):container.remove(force=True,v=True)
        network.remove();client.close()
