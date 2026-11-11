"""Opt-in real k3d registry pulls and data recovery after cluster recreation."""
import base64
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import uuid

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.getenv('TEORIA_TEST_K3D') != '1', reason='explicit isolated k3d lifecycle test',
)
ROOT = Path(__file__).resolve().parents[3]


def test_registry_pull_and_retained_volume_survive_cluster_recreation(tmp_path):
    for tool in ('docker', 'k3d', 'openssl'):
        assert shutil.which(tool), f'{tool} is required'

    def run(*args, **kwargs):
        result = subprocess.run(args, text=True, capture_output=True, timeout=300, **kwargs)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    for image in ('busybox:1.36', 'python:3.12-slim'):
        if subprocess.run(['docker', 'image', 'inspect', image], capture_output=True).returncode:
            run('docker', 'pull', image)

    suffix = uuid.uuid4().hex[:10]
    name = 'teoria-check-' + suffix
    registry = 'k3d-' + name + '-images'
    host_path = '/tmp/' + name
    registry_port = random.randint(20000, 50000)
    config = yaml.safe_load((ROOT / 'deploy/kubernetes/k3d/cluster.yaml').read_text())
    config['metadata']['name'] = name
    config['kubeAPI']['hostPort'] = str(registry_port + 1)
    config['ports'] = []
    config['volumes'][0]['volume'] = host_path + '/storage:/var/lib/rancher/k3s/storage'
    config['registries']['create'].update(
        name=registry, hostPort=str(registry_port),
        volumes=[host_path + '/registry:/var/lib/registry'],
    )
    config['registries']['config'] = yaml.safe_dump({'mirrors': {
        'localhost:5111': {'endpoint': ['http://' + registry + ':5000']},
    }})
    config_path = tmp_path / 'cluster.yaml'
    config_path.write_text(yaml.safe_dump(config))
    node = 'k3d-' + name + '-server-0'

    def kubectl(*args, **kwargs):
        return run('docker', 'exec', '-i', node, 'kubectl', *args, **kwargs)

    def apply(resource):
        kubectl('apply', '-f', '-', input=json.dumps(resource))

    def mount_pod(command):
        apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'storage-check'}, 'spec': {
            'restartPolicy': 'Never', 'containers': [{
                'name': 'check', 'image': 'localhost:5111/smoke:check',
                'command': ['sh', '-ec', command],
                'volumeMounts': [{'name': 'data', 'mountPath': '/data'}],
            }], 'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'check'}}],
        }})
        kubectl('wait', '--for=jsonpath={.status.phase}=Succeeded', 'pod/storage-check', '--timeout=120s')

    def verify_local_tls_and_dns():
        certificate, key = tmp_path / 'tls.crt', tmp_path / 'tls.key'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-keyout', str(key), '-out', str(certificate), '-subj', '/CN=teoria.localhost',
            '-addext', 'subjectAltName=DNS:teoria.localhost')
        apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'local-tls'},
               'type': 'kubernetes.io/tls', 'data': {
                   'tls.crt': base64.b64encode(certificate.read_bytes()).decode(),
                   'tls.key': base64.b64encode(key.read_bytes()).decode(),
               }})
        apply(yaml.safe_load((ROOT / 'deploy/kubernetes/k3d/dns.yaml').read_text()))
        kubectl('-n', 'kube-system', 'rollout', 'restart', 'deployment/coredns')
        kubectl('-n', 'kube-system', 'rollout', 'status', 'deployment/coredns', '--timeout=120s')
        kubectl('-n', 'kube-system', 'wait', '--for=condition=Complete', 'job/helm-install-traefik', '--timeout=120s')
        kubectl('-n', 'kube-system', 'rollout', 'status', 'deployment/traefik', '--timeout=120s')
        kubectl('delete', 'pod/storage-check', '--wait=true')
        apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
            'name': 'web', 'labels': {'app': 'web'},
        }, 'spec': {'containers': [{'name': 'web', 'image': 'localhost:5111/smoke:check',
                                   'command': ['sh', '-ec', 'mkdir -p /www; printf "local ingress" > /www/health; exec httpd -f -p 8080 -h /www']}]}})
        kubectl('wait', '--for=condition=Ready', 'pod/web', '--timeout=120s')
        apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'web'},
               'spec': {'selector': {'app': 'web'}, 'ports': [{'port': 80, 'targetPort': 8080}]}})
        apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress', 'metadata': {'name': 'web'},
               'spec': {'ingressClassName': 'traefik',
                        'tls': [{'hosts': ['teoria.localhost'], 'secretName': 'local-tls'}],
                        'rules': [{'host': 'teoria.localhost', 'http': {'paths': [{
                            'path': '/', 'pathType': 'Prefix', 'backend': {
                                'service': {'name': 'web', 'port': {'number': 80}},
                            },
                        }]}}]}})
        image = f'localhost:{registry_port}/probe:check'
        run('docker', 'tag', 'python:3.12-slim', image)
        run('docker', 'push', image)
        probe = '''import ssl,time,urllib.request,urllib.error
context=ssl.create_default_context(cafile='/tls/tls.crt')
for attempt in range(30):
    try:
        response=urllib.request.urlopen('https://teoria.localhost/health',context=context,timeout=5)
        assert response.read() == b'local ingress'
        break
    except (OSError,urllib.error.URLError):
        if attempt == 29: raise
        time.sleep(1)
'''
        apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'tls-probe'}, 'spec': {
            'restartPolicy': 'Never', 'containers': [{
                'name': 'probe', 'image': 'localhost:5111/probe:check', 'command': ['python', '-c', probe],
                'volumeMounts': [{'name': 'tls', 'mountPath': '/tls', 'readOnly': True}],
            }], 'volumes': [{'name': 'tls', 'secret': {'secretName': 'local-tls',
                           'items': [{'key': 'tls.crt', 'path': 'tls.crt'}]}}],
        }})
        kubectl('wait', '--for=jsonpath={.status.phase}=Succeeded', 'pod/tls-probe', '--timeout=120s')

    try:
        for attempt in range(2):
            run('k3d', 'cluster', 'create', '--config', str(config_path))
            kubectl('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=120s')
            storage = yaml.safe_load((ROOT / 'deploy/kubernetes/k3d/storage.yaml').read_text())
            apply(storage)
            if attempt == 0:
                image = f'localhost:{registry_port}/smoke:check'
                run('docker', 'tag', 'busybox:1.36', image)
                run('docker', 'push', image)
            apply({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'check'}, 'spec': {
                'storageClassName': 'teoria-local', 'accessModes': ['ReadWriteOnce'],
                'resources': {'requests': {'storage': '1Mi'}},
            }})
            mount_pod('echo retained > /data/proof' if attempt == 0 else 'test "$(cat /data/proof)" = retained')
            pv = json.loads(kubectl('get', 'pv', '-o', 'json'))['items'][0]
            assert pv['spec']['persistentVolumeReclaimPolicy'] == 'Retain'
            assert pv['spec']['hostPath']['path'].rstrip('/').endswith('/default/check')
            if attempt == 0:
                verify_local_tls_and_dns()
            run('k3d', 'cluster', 'delete', name)
            # k3d normally removes its managed registry with the cluster.
            registries = json.loads(run('k3d', 'registry', 'list', '-o', 'json'))
            if any(r['name'] == registry for r in registries):
                run('k3d', 'registry', 'delete', registry)
    finally:
        subprocess.run(['k3d', 'cluster', 'delete', name], capture_output=True, timeout=120)
        subprocess.run(['k3d', 'registry', 'delete', registry], capture_output=True, timeout=120)
        # Remove only this test's Docker-host bind directory contents.
        subprocess.run(['docker', 'run', '--rm', '-v', host_path + ':/data', 'busybox:1.36',
                        'sh', '-ec', 'rm -rf /data/storage /data/registry'], capture_output=True, timeout=60)
