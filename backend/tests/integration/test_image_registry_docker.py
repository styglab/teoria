"""Opt-in Registry HTTP upstream and shared proxy HTTP/TLS upload/read smoke test.

TEORIA_TEST_REGISTRY_DOCKER=1 enables the test. Requires registry:3.1.2 and a
Teoria Admin image containing httpx, configurable with TEORIA_REGISTRY_TEST_CLIENT_IMAGE.
All credentials, image manifests, volumes and networks are synthetic and isolated.
"""

import io
import os
import secrets
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("TEORIA_TEST_REGISTRY_DOCKER") != "1",
    reason="explicit Registry Docker test",
)


def test_registry_proxy_upload_catalog_and_persistence(tmp_path):
    docker = pytest.importorskip("docker")
    import crypt

    root = Path(__file__).resolve().parents[3]
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=registry-proxy",
            "-addext",
            "subjectAltName=DNS:registry-proxy",
            "-keyout",
            str(tmp_path / "tls.key"),
            "-out",
            str(tmp_path / "tls.crt"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    password = "synthetic-registry-test"
    hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_BLOWFISH))
    client = docker.from_env()
    name = "teoria-registry-test-" + uuid.uuid4().hex[:8]
    network = client.networks.create(name)
    volume = client.volumes.create(name + "-data")
    containers = []

    def put(container, destination, files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            for filename, content in files.items():
                info = tarfile.TarInfo(filename)
                info.size = len(content)
                info.mode = 0o600 if filename.endswith(".key") else 0o644
                archive.addfile(info, io.BytesIO(content))
        container.put_archive(destination, data.getvalue())

    try:
        registry = client.containers.create(
            "registry:3.1.2",
            ["serve", "/etc/distribution/config.yaml"],
            name=name,
            network=network.name,
            environment={
                "REGISTRY_HTTP_SECRET": secrets.token_hex(32),
                "OTEL_TRACES_EXPORTER": "none",
            },
            volumes={volume.name: {"bind": "/var/lib/registry", "mode": "rw"}},
            mem_limit="512m",
            nano_cpus=1000000000,
        )
        containers.append(registry)
        network.disconnect(registry)
        network.connect(registry, aliases=["image-registry"])
        put(
            registry,
            "/etc/distribution",
            {
                "config.yaml": (
                    root / "deploy/compose/registry/config.yaml"
                ).read_bytes()
            },
        )
        put(
            registry,
            "/run",
            {
                "registry/htpasswd": f"test:{hashed}\n".encode(),
            },
        )
        registry.start()
        proxy = client.containers.create(
            "nginx:1.27-alpine", network=network.name,
            mem_limit="128m", nano_cpus=500000000,
        )
        containers.append(proxy)
        network.disconnect(proxy)
        network.connect(proxy, aliases=["registry-proxy"])
        proxy_config = (root / "deploy/compose/nginx/nginx.conf").read_text().replace(
            "listen 80 default_server;",
            "listen 80 default_server;\n    listen 443 ssl;\n    ssl_certificate /tmp/tls.crt;\n    ssl_certificate_key /tmp/tls.key;",
        )
        put(proxy, "/etc/nginx/conf.d", {"default.conf": proxy_config.encode()})
        put(proxy, "/tmp", {"tls.crt": (tmp_path / "tls.crt").read_bytes(),
                            "tls.key": (tmp_path / "tls.key").read_bytes()})
        proxy.start()
        helper = client.containers.create(
            os.getenv(
                "TEORIA_REGISTRY_TEST_CLIENT_IMAGE", "teoria-platform-admin:0.1.0"
            ),
            ["sleep", "300"],
            network=network.name,
            user="root",
            mem_limit="512m",
            nano_cpus=1000000000,
        )
        containers.append(helper)
        put(
            helper,
            "/tmp",
            {
                "ca.crt": (tmp_path / "tls.crt").read_bytes(),
                "image_registry.py": (
                    root / "backend/src/teoria/integrations/image_registry.py"
                ).read_bytes(),
            },
        )
        helper.start()
        deadline = time.monotonic() + 30
        while registry.exec_run(
            ["wget", "--quiet", "--spider", "http://127.0.0.1:5001/debug/health"]
        ).exit_code:
            assert time.monotonic() < deadline, "Registry startup timed out"
            time.sleep(1)
        while proxy.exec_run(["wget", "--quiet", "--spider", "http://127.0.0.1/health"]).exit_code:
            assert time.monotonic() < deadline, "Proxy startup timed out"
            time.sleep(1)
        code = r"""
import asyncio, base64, hashlib, json, os, ssl, sys, urllib.request, urllib.error
sys.path.insert(0, '/tmp')
import httpx
from image_registry import ImageRegistryClient
base=sys.argv[1]
context=ssl.create_default_context(cafile='/tmp/ca.crt')
auth='Basic '+base64.b64encode(b'test:synthetic-registry-test').decode()
def request(path, method='GET', content=None, headers=None):
    req=urllib.request.Request(base+path, data=content, method=method, headers={'Authorization':auth, **(headers or {})})
    return urllib.request.urlopen(req, context=context, timeout=10)
try:
    urllib.request.urlopen(base+'/v2/', context=context)
    raise AssertionError('Unauthenticated registry access succeeded')
except urllib.error.HTTPError as error:
    assert error.code==401
# Exceed nginx's default 1 MiB body limit and follow resumable upload Locations.
large=os.urandom(2*1024*1024)
large_digest='sha256:'+hashlib.sha256(large).hexdigest()
location=request('/v2/models/churn/blobs/uploads/', 'POST', b'').headers['Location']
assert location.startswith('/v2/')
for chunk in (large[:1024*1024+64],large[1024*1024+64:]):
    response=request(location,'PATCH',chunk,{'Content-Type':'application/octet-stream'})
    location=response.headers['Location']
    assert location.startswith('/v2/')
separator='&' if '?' in location else '?'
request(location+separator+'digest='+large_digest,'PUT',b'',{'Content-Type':'application/octet-stream'})
assert request('/v2/models/churn/blobs/'+large_digest).read()==large
config=json.dumps({'architecture' :'amd64','os':'linux','rootfs':{'type':'layers','diff_ids':[]},'config':{}}).encode()
digest='sha256:'+hashlib.sha256(config).hexdigest()
for repository in ('teoria/smoke', 'models/churn'):
    upload=request('/v2/'+repository+'/blobs/uploads/', 'POST', b'')
    location=upload.headers['Location'].removeprefix(base)
    separator='&' if '?' in location else '?'
    request(location+separator+'digest='+digest, 'PUT', config, {'Content-Type':'application/octet-stream'})
    manifest=json.dumps({'schemaVersion':2,'mediaType':'application/vnd.docker.distribution.manifest.v2+json','config':{'mediaType':'application/vnd.docker.container.image.v1+json','size':len(config),'digest':digest},'layers':[]}).encode()
    request('/v2/'+repository+'/manifests/v1', 'PUT', manifest, {'Content-Type':'application/vnd.docker.distribution.manifest.v2+json'})
async def verify():
    async with httpx.AsyncClient(verify=context) as http:
        registry=ImageRegistryClient(http,url=base,public_host='registry.example.com',username='test',password='synthetic-registry-test')
        catalog=await registry.repositories(limit=1)
        assert len(catalog['items'])==1 and catalog['next']
        page=await registry.repositories(after=catalog['next'],limit=1)
        assert len(page['items'])==1
        assert (await registry.tags('models/churn'))['items']==['v1']
        result=await registry.manifest('models/churn','v1')
        assert result['image'].startswith('registry.example.com/models/churn@sha256:')
        assert (await registry.manifest('models/churn',result['digest']))['digest']==result['digest']
        print('Authenticated proxy upload, pagination, tag and verified digest read passed')
asyncio.run(verify())
"""
        for base in ("http://registry-proxy", "https://registry-proxy"):
            result = helper.exec_run(["python", "-c", code, base])
            assert result.exit_code == 0, result.output.decode()
        registry.restart(timeout=5)
        deadline = time.monotonic() + 30
        while registry.exec_run(
            ["wget", "--quiet", "--spider", "http://127.0.0.1:5001/debug/health"]
        ).exit_code:
            assert time.monotonic() < deadline
            time.sleep(1)
        verify = code[code.index("async def verify():") :]
        prelude = code[: code.index("# Exceed nginx")]
        result = helper.exec_run(["python", "-c", prelude + verify, "https://registry-proxy"])
        assert result.exit_code == 0, result.output.decode()
    finally:
        for container in reversed(containers):
            container.remove(force=True)
        network.remove()
        volume.remove()
        client.close()
