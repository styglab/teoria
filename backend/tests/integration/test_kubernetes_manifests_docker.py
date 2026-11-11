"""Opt-in API-only schema validation without any controller-specific CRDs."""
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark=pytest.mark.skipif(os.getenv('TEORIA_TEST_KUBERNETES_API_DOCKER')!='1',reason='explicit isolated Kubernetes API test')


def test_generic_manifests_validate_without_traefik(tmp_path):
    docker=pytest.importorskip('docker')
    client=docker.from_env()
    root=Path(__file__).resolve().parents[3]
    kubectl=os.getenv('TEORIA_TEST_KUBECTL') or shutil.which('kubectl')
    assert kubectl,'kubectl is required for offline rendering'
    (tmp_path/'kubectl').symlink_to(kubectl)
    environment={**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH']}
    server=None
    try:
        server=client.containers.run('rancher/k3s:v1.37.1-k3s1',
            ['server','--disable-agent','--disable','traefik','--disable','servicelb','--disable','metrics-server','--disable','local-storage'],
            name='teoria-api-check-'+uuid.uuid4().hex[:10],privileged=True,detach=True,
            tmpfs={'/run':'','/var/run':''},mem_limit='2g',nano_cpus=2_000_000_000)
        for _ in range(120):
            result=server.exec_run(['kubectl','get','--raw=/readyz'])
            if result.exit_code==0:break
            time.sleep(1)
        else:pytest.fail('isolated Kubernetes API did not become ready')
        for namespace in ('teoria','teoria-pipelines','teoria-models'):
            assert server.exec_run(['kubectl','create','namespace',namespace]).exit_code==0
        for module in ('mlops','semantic'):
            args=['bash',str(root/'deploy/kubernetes/deploy.sh'),'ghcr.io/example/teoria','a'*40,'teoria.example.com',
                '--modules',module,'--overlay','generic','--storage-class','test-csi','--ingress-class','public','--render']
            if module=='semantic':args += ['--shared-storage-class','test-rwx']
            else:args += ['--with-model-registry','registry.example.com']
            rendered=subprocess.run(args,env=environment,text=True,capture_output=True,check=True).stdout
            result=subprocess.run(['docker','exec','-i',server.name,'kubectl','apply','--dry-run=server','-f','-'],
                input=rendered,capture_output=True,text=True)
            assert result.returncode==0,result.stderr
    finally:
        if server is not None:server.remove(force=True,v=True)
        client.close()
