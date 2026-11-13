"""Fault injection through the real apply/recover sequence, using isolated operator state."""
import base64
import copy
import json
from pathlib import Path

import pytest
import yaml

from teoria.entrypoints.k3d_remote_access import (
    API_ENV, PROXY, REGISTRY_CA, REGISTRY_FILE, ROLE, SECRET_NAMES,
    DevelopmentAccess, configuration_text, external_addresses, secret_updates,
)


def encoded(value):
    return base64.b64encode(value.encode()).decode()


def secret(name, data):
    return {'metadata': {'name': name, 'resourceVersion': '1'}, 'data': {k: encoded(v) for k, v in data.items()}}


class IsolatedAccess(DevelopmentAccess):
    """Only external commands are simulated; state selection and recovery are production code."""
    def __init__(self, root, failure=None):
        super().__init__(root)
        self.calls, self.failure = [], failure
        chart = root/'deploy/kubernetes/harbor/chart.json'
        chart.parent.mkdir(parents=True)
        chart.write_text((Path(__file__).resolve().parents[3]/'deploy/kubernetes/harbor/chart.json').read_text())
        self.previous = external_addresses('203.0.113.1')
        self.desired = external_addresses('203.0.113.2', 19443, 19444)
        self.directory.mkdir(parents=True)
        self.local.joinpath('harbor.crt').write_text('synthetic CA')
        self.local.joinpath('access.json').write_text('{"other":"keep","platform_url":"old"}')
        self.local.joinpath('remote_access.env').write_text(configuration_text(self.previous))
        self.directory.joinpath('config.json').write_text(json.dumps(self.previous))
        self.resources = {
            ('teoria', 'secret', 'teoria-secrets'): secret('teoria-secrets', {
                'TEORIA_APP_DATABASE_URL': 'private-db-owner', 'TEORIA_IMAGE_REGISTRY_URL': self.previous['harbor_url'],
                'TEORIA_IMAGE_REGISTRY_PUBLIC_HOST': '203.0.113.1:18444',
                'TEORIA_ADMIN_API_TOKEN': 'synthetic-admin', 'PREFECT_API_AUTH_STRING': 'synthetic:prefect'}),
            ('teoria', 'secret', 'model-control'): secret('model-control', {'TEORIA_MODEL_ALLOWED_REGISTRIES': 'other.registry', 'UNRELATED': 'keep'}),
            ('teoria', 'secret', 'teoria-registry'): secret('teoria-registry', {'.dockerconfigjson': json.dumps({'auths': {'harbor.teoria.localhost': {'auth': 'synthetic-login'}, 'other.registry': {'auth': 'keep'}}})}),
            ('teoria-models', 'secret', 'model-images'): secret('model-images', {'.dockerconfigjson': json.dumps({'auths': {'harbor.teoria.localhost': {'auth': 'synthetic-login'}}})}),
            ('teoria', 'deployment', 'admin-api'): {'metadata': {'resourceVersion': '1'}, 'spec': {'template': {'spec': {'containers': [{'name': 'admin-api', 'env': [
                {'name': API_ENV[0], 'valueFrom': {'secretKeyRef': {'name': 'teoria-secrets', 'key': API_ENV[0]}}},
                {'name': 'UNRELATED', 'value': 'keep'},
            ]}]}}}},
        }
        self.original = copy.deepcopy(self.resources)
        self.containers = {PROXY: {'Id': 'original', 'State': {'Running': True}, 'Config': {'Labels': {'io.teoria.role': ROLE}}}}
        self.revision = 7
        self.helm_url = self.previous['harbor_url']
        self.node = {REGISTRY_FILE: yaml.safe_dump({'mirrors': {'other.registry': {'endpoint': ['https://keep']}}, 'configs': {'other.registry': {'auth': {'password': 'keep'}}}})}
        self.original_node = copy.deepcopy(self.node)
        self.daemon = None

    def fail(self, name):
        if self.failure == name:
            self.failure = None
            raise RuntimeError('synthetic failure')

    def prepare(self, settings):
        self.calls.append('prepared-and-validated')
        self.fail('prepare')
        release = self.directory / 'release_test'
        release.joinpath('tls').mkdir(parents=True)
        release.joinpath('tls/ca.crt').write_text('synthetic CA')
        release.joinpath('harbor_values.json').write_text('{}')
        source = {name: self.get(namespace, 'secret', name) for namespace, name in SECRET_NAMES}
        admin = self.get('teoria', 'deployment', 'admin-api')
        files = [self.local / 'remote_access.env', self.directory / 'config.json', self.local / 'access.json', self.directory / 'tls/ca.crt']
        host = settings['harbor_url'].removeprefix('https://')
        return {'release': str(release), 'settings': settings, 'touched': [], 'before': {
            'secrets': source, 'updates': secret_updates(settings, source), 'admin_env': {e['name']: e for e in admin['spec']['template']['spec']['containers'][0]['env'] if e['name'] in API_ENV},
            'files': {str(p): base64.b64encode(p.read_bytes()).decode() if p.exists() else None for p in files},
            'ingress': None, 'ingress_spec': {'ingressClassName': 'traefik', 'rules': []}, 'helm_revision': self.revision,
            'proxy_id': 'original', 'proxy_running': True, 'backup_proxy': PROXY + '-previous-test',
            'node_ca': None, 'host_path': '/host/' + host, 'host_file': None, 'daemon_ca': None,
        }}

    def get(self, namespace, kind, name):
        return copy.deepcopy(self.resources.get((namespace, kind, name)))

    def patch(self, namespace, kind, name, value, *, patch_type='merge'):
        resource = self.resources[namespace, kind, name]
        self.calls.append('patch:' + name)
        expected = value.get('metadata', {}).get('resourceVersion')
        assert expected is None or expected == resource['metadata']['resourceVersion']
        if kind == 'secret':
            for key, body in value['data'].items():
                if body is None:
                    resource['data'].pop(key, None)
                else:
                    resource['data'][key] = body
        else:
            container = resource['spec']['template']['spec']['containers'][0]
            for item in value['spec']['template']['spec']['containers'][0]['env']:
                container['env'] = [e for e in container['env'] if e['name'] != item['name']]
                if item.get('$patch') != 'delete':
                    container['env'].append({k: v for k, v in item.items() if v is not None})
        resource['metadata']['resourceVersion'] = str(int(resource['metadata']['resourceVersion']) + 1)
        self.fail('patch:' + name)

    def apply(self, item):
        self.resources['harbor', 'ingress', 'harbor-ip-access'] = copy.deepcopy(item)
        self.fail('ingress')

    def inspect(self, name):
        return copy.deepcopy(self.containers.get(name))

    def node_file(self, path, content=None, *, remove=False):
        if content is not None:
            self.node[path] = content
            self.fail('node')
        elif remove:
            self.node.pop(path, None)
        else:
            return self.node.get(path)

    def daemon_ca(self, host, content=None, *, remove=False):
        if content is not None or remove:
            self.daemon = None if remove else content
            self.fail('daemon')
        return self.daemon

    def proxy_arguments(self, release):
        return []

    def verify(self, settings, release=None):
        self.calls.append('verify')
        self.fail('verify')

    def rollout(self):
        self.calls.append('rollout')
        self.fail('rollout')

    def kubectl(self, *args, body=None):
        if 'delete' in args:
            self.resources.pop(('harbor', 'ingress', 'harbor-ip-access'), None)
            return ''
        raise AssertionError(args)

    def run(self, *args, body=None):
        self.calls.append(' '.join(map(str, args[:3])))
        if args[:2] == ('bash', self.root / 'deploy/kubernetes/harbor/deploy.sh'):
            self.revision += 1
            self.helm_url = self.desired['harbor_url']
            self.fail('helm')
        elif args[:2] == ('helm', 'history'):
            return json.dumps([{'revision': self.revision}])
        elif args[:2] == ('helm', 'rollback'):
            self.revision += 1
            self.helm_url = self.previous['harbor_url']
        elif args[:2] in [('docker', 'stop'), ('docker', 'start')]:
            container = next(c for c in self.containers.values() if c['Id'] == args[2])
            container['State']['Running'] = args[1] == 'start'
        elif args[:2] == ('docker', 'rename'):
            old = next(k for k, c in self.containers.items() if c['Id'] == args[2])
            self.containers[args[3]] = self.containers.pop(old)
        elif args[:2] == ('docker', 'rm'):
            identifier = args[-1]
            key = next(k for k, c in self.containers.items() if c['Id'] == identifier)
            self.containers.pop(key)
        elif args[:2] == ('docker', 'run'):
            self.fail('bind')
            self.containers[PROXY] = {'Id': 'candidate', 'State': {'Running': True}, 'Config': {'Labels': {'io.teoria.role': ROLE, 'io.teoria.transaction': 'release_test'}}}
        return ''


@pytest.mark.parametrize('failure', ['prepare', 'ingress', 'helm', 'node', 'daemon', 'patch:teoria-secrets', 'patch:model-control', 'patch:model-images', 'patch:admin-api', 'rollout', 'bind', 'verify'])
def test_each_failed_stage_restores_owned_values_and_original_proxy(tmp_path, failure):
    access = IsolatedAccess(tmp_path, failure)
    before_receipt = access.directory.joinpath('config.json').read_bytes()
    with pytest.raises(RuntimeError):
        access.expose(access.desired)
    assert access.containers == {PROXY: {'Id': 'original', 'State': {'Running': True}, 'Config': {'Labels': {'io.teoria.role': ROLE}}}}
    assert access.helm_url == access.previous['harbor_url']
    assert yaml.safe_load(access.node[REGISTRY_FILE]) == yaml.safe_load(access.original_node[REGISTRY_FILE])
    assert access.daemon is None
    assert access.directory.joinpath('config.json').read_bytes() == before_receipt
    assert not access.directory.joinpath('pending.json').exists()
    for namespace, name in SECRET_NAMES:
        assert access.get(namespace, 'secret', name)['data'] == access.original[namespace, 'secret', name]['data']
    before_env = access.original['teoria', 'deployment', 'admin-api']['spec']['template']['spec']['containers'][0]['env']
    after_env = access.get('teoria', 'deployment', 'admin-api')['spec']['template']['spec']['containers'][0]['env']
    assert sorted(before_env, key=lambda e: e['name']) == sorted(after_env, key=lambda e: e['name'])
    assert access.calls[0] == 'prepared-and-validated'


def test_success_commits_config_only_after_verification_and_removes_secret_snapshot(tmp_path):
    access = IsolatedAccess(tmp_path)
    def verified(settings, release=None):
        assert json.loads(access.directory.joinpath('config.json').read_text()) == access.previous
        access.calls.append('verify')
    access.verify = verified
    access.expose(access.desired)
    assert json.loads(access.directory.joinpath('config.json').read_text()) == access.desired
    assert '19444' in access.local.joinpath('remote_access.env').read_text()
    assert not access.directory.joinpath('pending.json').exists()
    assert list(access.containers) == [PROXY]
    assert access.containers[PROXY]['Id'] == 'candidate'
    assert access.calls.index('prepared-and-validated') < access.calls.index('docker stop original') < access.calls.index('verify')
    assert 'synthetic-admin' not in access.directory.joinpath('release_test/transaction.json').read_text()
    assert not access.directory.joinpath('release_test/harbor_values.json').exists()


def test_failure_during_commit_restores_local_receipt(tmp_path, monkeypatch):
    import teoria.entrypoints.k3d_remote_access as module
    access = IsolatedAccess(tmp_path)
    original_write = module.write_private
    failed = False
    def write(path, data):
        nonlocal failed
        original_write(path, data)
        if Path(path) == access.local / 'remote_access.env' and not failed:
            failed = True
            raise OSError('synthetic disk failure after first commit write')
    monkeypatch.setattr(module, 'write_private', write)
    with pytest.raises(RuntimeError, match='previous configuration was restored'):
        access.expose(access.desired)
    assert json.loads(access.directory.joinpath('config.json').read_text()) == access.previous
    assert access.local.joinpath('remote_access.env').read_text() == configuration_text(access.previous)


def test_recovery_preserves_unrelated_concurrent_secret_changes(tmp_path):
    access = IsolatedAccess(tmp_path)
    access.journal = access.prepare(access.desired)
    access.save_journal()
    access.directory.joinpath('pending.json').write_text(json.dumps({'release': access.journal['release']}))
    for namespace, name in SECRET_NAMES:
        access.touch('secret:' + name)
        access.patch(namespace, 'secret', name, {'data': access.journal['before']['updates'][name]})
    access.resources['teoria', 'secret', 'teoria-secrets']['data']['TEORIA_APP_DATABASE_URL'] = encoded('rotated-owner')
    access.resources['teoria', 'secret', 'model-control']['data']['TEORIA_MODEL_ALLOWED_REGISTRIES'] = encoded('other.registry,203.0.113.2:19444,new.registry')
    registry = json.loads(base64.b64decode(access.resources['teoria', 'secret', 'teoria-registry']['data']['.dockerconfigjson']))
    registry['auths']['other.registry']['auth'] = 'rotated-other'
    access.resources['teoria', 'secret', 'teoria-registry']['data']['.dockerconfigjson'] = encoded(json.dumps(registry))
    access.journal = None  # Simulate a fresh --recover process reading the durable journal.
    access.recover()
    assert access.resources['teoria', 'secret', 'teoria-secrets']['data']['TEORIA_APP_DATABASE_URL'] == encoded('rotated-owner')
    assert base64.b64decode(access.resources['teoria', 'secret', 'model-control']['data']['TEORIA_MODEL_ALLOWED_REGISTRIES']).decode() == 'other.registry,new.registry'
    auths = json.loads(base64.b64decode(access.resources['teoria', 'secret', 'teoria-registry']['data']['.dockerconfigjson']))['auths']
    assert '203.0.113.2:19444' not in auths
    assert auths['other.registry']['auth'] == 'rotated-other'


def test_concurrent_owned_endpoint_change_keeps_journal_for_manual_recovery(tmp_path):
    access = IsolatedAccess(tmp_path)
    access.journal = access.prepare(access.desired)
    access.save_journal()
    access.directory.joinpath('pending.json').write_text(json.dumps({'release': access.journal['release']}))
    access.touch('secret:teoria-secrets')
    access.resources['teoria', 'secret', 'teoria-secrets']['data'][API_ENV[0]] = encoded('https://operator-changed.example')
    with pytest.raises(RuntimeError, match='incomplete'):
        access.recover()
    assert access.directory.joinpath('pending.json').exists()
    assert access.resources['teoria', 'secret', 'teoria-secrets']['data'][API_ENV[0]] == encoded('https://operator-changed.example')


def test_interrupted_helm_rollback_can_resume_from_persisted_intent(tmp_path):
    access = IsolatedAccess(tmp_path)
    access.journal = access.prepare(access.desired)
    before = access.journal['before']
    before['helm_external_url'] = access.previous['harbor_url']
    before['helm_rollback_revision'] = 9
    access.journal['touched'] = ['helm']
    access.save_journal()
    access.directory.joinpath('pending.json').write_text(json.dumps({'release': access.journal['release']}))
    # The Helm rollback completed, then the process stopped before saving its result.
    access.revision = 9
    original = access.run
    def run(*args, body=None):
        if args[:2] == ('helm', 'history'):
            return json.dumps([{'revision': 9, 'status': 'deployed'}])
        if args[:3] == ('helm', 'get', 'values'):
            return json.dumps({'externalURL': access.previous['harbor_url']})
        return original(*args, body=body)
    access.run = run
    access.journal = None
    access.recover()
    assert not access.directory.joinpath('pending.json').exists()
    assert not any('helm rollback' in call for call in access.calls)
