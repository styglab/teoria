"""Opt-in TLS/authenticated Distribution push/read and persistent storage smoke test.

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


def test_tls_registry_image_upload_catalog_and_persistence(tmp_path):
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
            "/CN=registry",
            "-addext",
            "subjectAltName=DNS:registry",
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
        network.connect(registry, aliases=["registry"])
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
                "registry/tls.crt": (tmp_path / "tls.crt").read_bytes(),
                "registry/tls.key": (tmp_path / "tls.key").read_bytes(),
            },
        )
        registry.start()
        helper = client.containers.create(
            os.getenv(
                "TEORIA_REGISTRY_TEST_CLIENT_IMAGE", "teoria-platform-admin:latest"
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
        code = r"""
import asyncio, base64, hashlib, json, ssl, sys, urllib.request, urllib.error
sys.path.insert(0, '/tmp')
import httpx
from image_registry import ImageRegistryClient
base='https://registry:5000'
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
config=json.dumps({'architecture':'amd64','os':'linux','rootfs':{'type':'layers','diff_ids':[]},'config':{}}).encode()
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
        print('Authenticated TLS upload, pagination, tag and verified digest read passed')
asyncio.run(verify())
"""
        result = helper.exec_run(["python", "-c", code])
        assert result.exit_code == 0, result.output.decode()
        registry.restart(timeout=5)
        deadline = time.monotonic() + 30
        while registry.exec_run(
            ["wget", "--quiet", "--spider", "http://127.0.0.1:5001/debug/health"]
        ).exit_code:
            assert time.monotonic() < deadline
            time.sleep(1)
        verify = code[code.index("async def verify():") :]
        prelude = code[: code.index("config=json.dumps")]
        result = helper.exec_run(["python", "-c", prelude + verify])
        assert result.exit_code == 0, result.output.decode()
    finally:
        for container in reversed(containers):
            container.remove(force=True)
        network.remove()
        volume.remove()
        client.close()
