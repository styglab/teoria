"""An isolated TLS proxy, fake ingress and streamed Registry upload; no real k3d access."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import time
import uuid

import pytest

from teoria.entrypoints.k3d_remote_access import external_addresses, nginx_configuration

pytestmark = pytest.mark.skipif(os.getenv('TEORIA_TEST_K3D_ACCESS_DOCKER') != '1', reason='explicit isolated k3d access proxy test')


def test_ip_proxy_tls_authentication_host_headers_and_streamed_registry_upload(tmp_path):
    docker = pytest.importorskip('docker')
    client = docker.from_env()
    name = 'teoria-access-check-' + uuid.uuid4().hex[:10]
    network = volume = None
    containers = []
    base = os.getenv('TEORIA_KUBERNETES_PROXY_CLIENT_IMAGE', 'teoria-platform-admin:0.1.0')
    client.images.get(base)
    client.images.get('nginx:1.27-alpine')
    certificate, key = tmp_path / 'server.crt', tmp_path / 'server.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(key), '-out', str(certificate), '-subj', '/CN=' + name,
                    '-addext', 'subjectAltName=DNS:' + name + ',DNS:teoria.localhost,DNS:harbor.teoria.localhost,IP:203.0.113.10'],
                   check=True, capture_output=True)
    backend = r'''
import hashlib,json,ssl
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def respond(self,status,body,challenge=None):
        data=json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Content-Type','application/json')
        if challenge:self.send_header('WWW-Authenticate',challenge)
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/v2/':return self.respond(401,{},'Bearer realm="https://harbor.example/service/token",service="harbor-registry"')
        if self.path=='/admin-api/v1/admin/auth/session' and self.headers.get('Authorization')!='Bearer synthetic-admin':return self.respond(401,{})
        if self.path in ('/mlflow/health','/prefect/api/health') and self.headers.get('Authorization')!='Basic b3BzOnN5bnRoZXRpYw==':return self.respond(401,{})
        self.respond(200,{'path':self.path,'host':self.headers['Host']})
    def do_POST(self):
        count=0;digest=hashlib.sha256();remaining=int(self.headers['Content-Length'])
        while remaining:
            data=self.rfile.read(min(65536,remaining));count+=len(data);remaining-=len(data);digest.update(data)
        self.respond(201,{'bytes':count,'sha256':digest.hexdigest(),'host':self.headers['Host']})
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('0.0.0.0',443),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain('/fixture/tls/server.crt','/fixture/tls/server.key')
server.socket=context.wrap_socket(server.socket,server_side=True)
server.serve_forever()
'''
    try:
        network = client.networks.create(name)
        volume = client.volumes.create(name=name)
        upstream = client.containers.create(base, ['python', '-c', backend], user='0', network=network.name,
                                            volumes={volume.name: {'bind': '/fixture', 'mode': 'rw'}})
        containers.append(upstream)
        network.disconnect(upstream)
        network.connect(upstream, aliases=['k3d-teoria-serverlb'])
        content = io.BytesIO()
        files = {
            'nginx.conf': nginx_configuration(external_addresses('203.0.113.10')).replace('/certs/', '/fixture/tls/').encode(),
            'tls/server.crt': certificate.read_bytes(), 'tls/server.key': key.read_bytes(),
            'tls/upstream_ca.crt': certificate.read_bytes(), 'tls/ca.crt': certificate.read_bytes(),
        }
        with tarfile.open(fileobj=content, mode='w') as archive:
            for filename, data in files.items():
                item = tarfile.TarInfo(filename);item.size=len(data);item.uid=item.gid=10001
                item.mode=0o600 if filename.endswith('.key') else 0o644
                archive.addfile(item,io.BytesIO(data))
        upstream.put_archive('/fixture', content.getvalue())
        upstream.start()
        proxy = client.containers.run('nginx:1.27-alpine', entrypoint=['nginx'],
            command=['-c', '/fixture/nginx.conf', '-g', 'daemon off;'], name=name,
            user='10001:10001', read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges'],
            tmpfs={'/tmp':'rw,noexec,nosuid,size=64m,uid=10001,gid=10001'}, network=network.name,
            volumes={volume.name:{'bind':'/fixture','mode':'ro'}}, detach=True)
        containers.append(proxy)
        helper = client.containers.run(base, ['python', '-c', 'import time;time.sleep(180)'],
            network=network.name, volumes={volume.name:{'bind':'/fixture','mode':'ro'}}, detach=True)
        containers.append(helper)
        deadline = time.monotonic() + 20
        ready = ['python', '-c', 'import httpx,ssl,sys;httpx.get(sys.argv[1],verify=ssl.create_default_context(cafile="/fixture/tls/ca.crt")).raise_for_status()', 'https://' + name + ':18443/health']
        while helper.exec_run(ready).exit_code:
            assert time.monotonic() < deadline, 'isolated proxy did not become ready'
            time.sleep(.2)
        assertions = r'''
import hashlib,httpx,ssl,sys
name=sys.argv[1];platform='https://'+name+':18443';harbor='https://'+name+':18444'
try:httpx.get(platform+'/health',trust_env=False)
except httpx.ConnectError:pass
else:raise AssertionError('untrusted certificate was accepted')
context=ssl.create_default_context(cafile='/fixture/tls/ca.crt')
with httpx.Client(verify=context,trust_env=False,follow_redirects=False,timeout=30) as client:
    assert client.get(platform+'/health').json()['host']=='teoria.localhost'
    assert client.get(platform+'/admin-api/v1/admin/auth/session').status_code==401
    assert client.get(platform+'/admin-api/v1/admin/auth/session',headers={'Authorization':'Bearer synthetic-admin'}).status_code==200
    assert client.get(platform+'/mlflow/health').status_code==401
    assert client.get(platform+'/mlflow/health',auth=('ops','synthetic')).status_code==200
    assert client.get(platform+'/prefect/api/health',auth=('ops','synthetic')).status_code==200
    assert client.get(harbor+'/v2/').status_code==401
    assert 'Bearer ' in client.get(harbor+'/v2/').headers['WWW-Authenticate']
    assert client.get(harbor+'/api/v2.0/health').json()['host']==name+':18444'
    chunk=b'x'*262144;count=128
    response=client.post(harbor+'/v2/test/blobs/uploads/',content=(chunk for _ in range(count)),headers={'Content-Length':str(len(chunk)*count)})
    assert response.status_code==201,response.text
    assert response.json()['bytes']==len(chunk)*count
    digest=hashlib.sha256()
    for _ in range(count):digest.update(chunk)
    assert response.json()['sha256']==digest.hexdigest()
print('TLS verification, authorization, Host preservation and 32 MiB streamed upload passed')
'''
        result = helper.exec_run(['python', '-c', assertions, name])
        assert result.exit_code == 0, result.output.decode()
    finally:
        for container in reversed(containers):
            container.remove(force=True, v=True)
        if volume is not None:volume.remove()
        if network is not None:network.remove()
        client.close()
