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
    if module=='mlops':args += ['--model-registry-host','registry.example.com']
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
    assert any(r['apiVersion'].startswith('traefik') for r in direct) == (module == 'semantic')
    ui=next(r for r in direct if r['kind']=='Deployment' and r['metadata']['name']=='admin-ui')
    assert bool(ui['spec']['template']['spec']['containers'][0].get('command')) == (module == 'mlops')


def test_generic_default_storage_class_is_left_to_the_cluster(kubectl):
    resources=render(kubectl,'generic','mlops')
    assert all('storageClassName' not in r['spec'] for r in resources if r['kind']=='PersistentVolumeClaim')
    assert all('ingressClassName' not in r['spec'] for r in resources if r['kind']=='Ingress')
    deployments=[r for r in resources if r['kind'] in ('Deployment','StatefulSet')]
    assert len(deployments)==9
    assert not any(r['metadata']['name'] in ('postgres','opa','policy-control-plane','demo-inference') for r in deployments)


@pytest.mark.parametrize('overlay', ['generic', 'k3s', 'k3d'])
def test_registry_is_external_and_mlflow_keeps_authenticated_proxy(kubectl, overlay):
    resources = render(kubectl, overlay, 'mlops')
    assert not any(r['metadata']['name'] in {'image-registry', 'registry-data', 'mlflow-auth'} for r in resources)
    admin = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'admin-api')
    environment = {item['name']: item for item in admin['spec']['template']['spec']['containers'][0]['env']}
    assert environment['TEORIA_IMAGE_REGISTRY_URL']['value'] == 'https://registry.example.com'
    assert environment['TEORIA_IMAGE_REGISTRY_PUBLIC_HOST']['value'] == 'registry.example.com'
    assert 'valueFrom' not in environment['TEORIA_IMAGE_REGISTRY_PUBLIC_HOST']
    assert 'valueFrom' not in environment['TEORIA_IMAGE_REGISTRY_URL']
    config = next(r for r in resources if r['kind'] == 'ConfigMap' and 'default.conf.template' in r.get('data', {}))
    assert 'auth_request /_operations_auth' in config['data']['default.conf.template']


def test_k3d_mlops_defaults_to_shared_development_registry(kubectl):
    result = subprocess.run(['bash', str(KUBE / 'deploy.sh'), 'localhost:5111/teoria', 'a'*40,
                             'teoria.localhost', '--overlay', 'k3d', '--modules', 'mlops', '--render'],
                            env=kubectl, text=True, capture_output=True, check=True)
    resources = [r for r in yaml.safe_load_all(result.stdout) if r]
    admin = next(r for r in resources if r['kind'] == 'Deployment' and r['metadata']['name'] == 'admin-api')
    environment = {e['name']: e.get('value') for e in admin['spec']['template']['spec']['containers'][0]['env']}
    assert environment['TEORIA_IMAGE_REGISTRY_URL'] == 'http://k3d-teoria-images:5000'
    assert environment['TEORIA_IMAGE_REGISTRY_PUBLIC_HOST'] == 'localhost:5111'
    assert not any(r['metadata']['name'] in {'image-registry', 'registry-data'} for r in resources)


@pytest.mark.parametrize('module', ['semantic', 'mlops'])
def test_k3d_shares_k3s_workloads_and_uses_retained_local_storage(kubectl, module):
    local = render(kubectl, 'k3d', module)
    production = render(kubectl, 'k3s', module)
    assert {identity(r) for r in local} == {identity(r) for r in production}
    claims = [r for r in local if r['kind'] == 'PersistentVolumeClaim']
    assert claims
    assert all(r['spec']['storageClassName'] == 'teoria-local' for r in claims)
    assert all(r['spec']['accessModes'] == ['ReadWriteOnce'] for r in claims)
    if module == 'semantic':
        admin = next(r for r in local if r['kind'] == 'Deployment' and r['metadata']['name'] == 'admin-api')
        volume = next(v for v in admin['spec']['template']['spec']['volumes'] if v['name'] == 'local-tls')
        assert volume['secret']['items'] == [{'key': 'tls.crt', 'path': 'tls.crt'}]


def test_local_registry_images_are_also_used_by_later_prefect_jobs(kubectl):
    result = subprocess.run([
        'bash', str(KUBE / 'deploy.sh'), 'localhost:5111/teoria', 'a' * 40,
        'teoria.localhost', '--overlay', 'k3d', '--render',
    ], env=kubectl, text=True, capture_output=True, check=True)
    resources = [r for r in yaml.safe_load_all(result.stdout) if r]
    register = next(r for r in resources if r['kind'] == 'Job' and r['metadata']['name'] == 'prefect-register')
    environment = {e['name']: e.get('value') for e in register['spec']['template']['spec']['containers'][0]['env']}
    assert environment['TEORIA_PIPELINE_JOB_IMAGE'] == 'localhost:5111/teoria/pipelines:' + 'a' * 40
    assert environment['TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE'] == 'localhost:5111/teoria/ingestion:' + 'a' * 40


@pytest.mark.parametrize('arguments',[['--overlay','unknown'],['--storage-class','csi;echo bad'],['--ingress-class','https://ingress'],['--cluster-domain','invalid/domain']])
def test_invalid_environment_options_fail_before_cluster_access(arguments):
    result=subprocess.run(['bash',str(KUBE/'deploy.sh'),'ghcr.io/example/teoria','a'*40,'teoria.example.com',*arguments],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Choose --overlay' in result.stderr or 'Invalid Kubernetes' in result.stderr
