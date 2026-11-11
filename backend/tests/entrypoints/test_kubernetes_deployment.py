"""Provider-independent rendering, stable K3s resource identities and safe offline review."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[3]
KUBE=ROOT/'deploy/kubernetes'


@pytest.fixture
def kubectl(tmp_path):
    executable=os.getenv('TEORIA_TEST_KUBECTL') or shutil.which('kubectl')
    if not executable:
        pytest.skip('kubectl is required for offline kustomize rendering')
    # Fail immediately if an offline test accidentally attempts cluster access.
    wrapper=tmp_path/'kubectl'
    wrapper.write_text('''#!/usr/bin/env python3
import os,sys
if len(sys.argv) < 2 or sys.argv[1] != 'kustomize':
    raise SystemExit('offline rendering attempted cluster access')
os.execv(os.environ['TEORIA_TEST_REAL_KUBECTL'], [os.environ['TEORIA_TEST_REAL_KUBECTL'], *sys.argv[1:]])
''')
    wrapper.chmod(0o755)
    return {**os.environ,'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],
            'TEORIA_TEST_REAL_KUBECTL':str(Path(executable).resolve()),'KUBECONFIG':str(tmp_path/'not-present')}


def render(environment, overlay, module, *options):
    script=KUBE/'deploy.sh'
    args=['bash',str(script),'ghcr.io/example/teoria','a'*40,'teoria.example.com','--modules',module,'--render']
    args += ['--overlay',overlay]
    if overlay=='generic' and module=='semantic':args += ['--shared-storage-class','cluster-rwx']
    if module=='mlops':args += ['--with-model-registry','registry.example.com']
    result=subprocess.run(args+list(options),env=environment,text=True,capture_output=True,check=True)
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def identity(resource):
    return resource['apiVersion'],resource['kind'],resource['metadata'].get('namespace',''),resource['metadata']['name']


def test_common_base_does_not_define_a_provider_or_storage_class():
    for file in (KUBE/'base').rglob('*.yaml'):
        assert 'traefik' not in file.read_text(),file
        for resource in yaml.safe_load_all(file.read_text()):
            if resource.get('kind')=='PersistentVolumeClaim':
                assert 'storageClassName' not in resource['spec'],file


@pytest.mark.parametrize('module',['semantic','mlops'])
def test_generic_overlay_has_only_standard_resources_and_complete_routing(kubectl,module):
    resources=render(kubectl,'generic',module,'--storage-class','cluster-csi','--ingress-class','public','--cluster-domain','corp.internal')
    assert all(not r['apiVersion'].startswith('traefik') for r in resources)
    for resource in resources:
        if resource['kind']=='PersistentVolumeClaim':
            shared=resource['metadata']['name'] in {'runtime-artifacts','opa-signing-keys','opa-bundles'}
            assert resource['spec']['storageClassName']==('cluster-rwx' if shared else 'cluster-csi')
            if shared:assert resource['spec']['accessModes']==['ReadWriteMany']
    ingress=[r for r in resources if r['kind']=='Ingress']
    assert all(r['spec']['ingressClassName']=='public' for r in ingress)
    ui=next(r for r in resources if r['kind']=='Deployment' and r['metadata']['name']=='admin-ui')
    pod=ui['spec']['template']['spec']
    assert pod['containers'][0]['command']==['/bin/sh','/etc/teoria_proxy/start.sh']
    assert next(e['value'] for e in pod['containers'][0]['env'] if e['name']=='TEORIA_CLUSTER_DOMAIN')=='corp.internal'
    config=next(r for r in resources if r['kind']=='ConfigMap' and 'default.conf.template' in r.get('data',{}))
    assert 'auth_request /_operations_auth' in config['data']['default.conf.template']
    assert 'location /prefect/api/' in config['data']['default.conf.template']
    assert 'location /admin-api/' in config['data']['default.conf.template']
    assert any(v['configMap']['name']==config['metadata']['name'] for v in pod['volumes'] if 'configMap' in v)
    assert len({identity(r) for r in resources})==len(resources)


@pytest.mark.parametrize('module',['semantic','mlops'])
def test_k3s_overlay_preserves_native_routing_and_storage(kubectl,module):
    direct=render(kubectl,'k3s',module)
    assert all(r['spec']['storageClassName']=='local-path' for r in direct if r['kind']=='PersistentVolumeClaim')
    assert any(r['apiVersion'].startswith('traefik') for r in direct)
    ui=next(r for r in direct if r['kind']=='Deployment' and r['metadata']['name']=='admin-ui')
    assert not ui['spec']['template']['spec']['containers'][0].get('command')


def test_generic_default_storage_class_is_left_to_the_cluster(kubectl):
    resources=render(kubectl,'generic','mlops')
    assert all('storageClassName' not in r['spec'] for r in resources if r['kind']=='PersistentVolumeClaim')
    assert all('ingressClassName' not in r['spec'] for r in resources if r['kind']=='Ingress')
    deployments=[r for r in resources if r['kind'] in ('Deployment','StatefulSet')]
    assert len(deployments)==10
    assert not any(r['metadata']['name'] in ('postgres','opa','policy-control-plane','demo-inference') for r in deployments)


@pytest.mark.parametrize('overlay', ['generic', 'k3s'])
def test_registry_uses_shared_edge_tls_and_internal_catalog_access(kubectl, overlay):
    resources = render(kubectl, overlay, 'mlops')
    ingress = next(r for r in resources if r['kind'] == 'Ingress' and r['metadata']['name'] == 'image-registry')
    assert ingress['spec']['rules'][0]['host'] == 'registry.example.com'
    assert ingress['spec']['rules'][0]['http']['paths'][0]['path'] == '/v2/'
    assert ingress['spec']['tls'][0]['secretName'] == 'teoria-tls'
    admin = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'admin-api')
    environment = {item['name']: item for item in admin['spec']['template']['spec']['containers'][0]['env']}
    assert environment['TEORIA_IMAGE_REGISTRY_URL'] == {'name': 'TEORIA_IMAGE_REGISTRY_URL', 'value': 'http://image-registry:5000'}
    assert environment['TEORIA_IMAGE_REGISTRY_PUBLIC_HOST']['value'] == 'registry.example.com'


@pytest.mark.parametrize('arguments',[['--overlay','unknown'],['--storage-class','csi;echo bad'],['--ingress-class','https://ingress'],['--cluster-domain','invalid/domain']])
def test_invalid_environment_options_fail_before_cluster_access(arguments):
    result=subprocess.run(['bash',str(KUBE/'deploy.sh'),'ghcr.io/example/teoria','a'*40,'teoria.example.com',*arguments],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Choose --overlay' in result.stderr or 'Invalid Kubernetes' in result.stderr
