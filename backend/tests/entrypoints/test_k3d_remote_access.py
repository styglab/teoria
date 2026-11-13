"""IP exposure is an explicit development profile with fixed TLS and port boundaries."""
import pytest
import yaml

from teoria.entrypoints.k3d_remote_access import DevelopmentAccess, external_addresses, nginx_configuration


@pytest.mark.parametrize('address', ['localhost', '0.0.0.0', '127.0.0.1', '224.0.0.1', '203.0.113.1;touch /tmp/bad'])
def test_invalid_bind_addresses_are_rejected(address):
    with pytest.raises(ValueError):
        external_addresses(address)


@pytest.mark.parametrize('ports', [(443, 18444), (18443, 18443), (18443, 65536)])
def test_ports_must_be_distinct_and_unprivileged(ports):
    with pytest.raises(ValueError):
        external_addresses('203.0.113.10', *ports)


def test_ip_routes_keep_harbor_public_host_and_verify_both_tls_connections():
    settings = external_addresses('203.0.113.10')
    config = nginx_configuration(settings)
    assert settings['platform_url'] == 'https://203.0.113.10:18443'
    assert settings['harbor_url'] == 'https://203.0.113.10:18444'
    assert 'proxy_ssl_verify on;' in config
    assert 'proxy_set_header Host $http_host;' in config
    assert 'proxy_ssl_name harbor.teoria.localhost;' in config
    assert 'proxy_set_header Host teoria.localhost;' in config
    assert 'client_max_body_size 0;' in config
    assert 'listen 6550' not in config


def test_node_registry_update_preserves_existing_operator_configuration(tmp_path, monkeypatch):
    access = DevelopmentAccess(tmp_path)
    existing = {'mirrors': {'other.internal': {'endpoint': ['https://mirror.internal']}},
                'configs': {'other.internal': {'auth': {'username': 'fixture', 'password': 'synthetic'}}}}
    calls = []
    def run(*args, body=None):
        calls.append((args, body))
        if args[-1:] == ('/etc/rancher/k3s/registries.yaml',) and body is None:
            return 'present\n' + yaml.safe_dump(existing)
        return ''
    monkeypatch.setattr(access, 'run', run)
    access.restore_node(external_addresses('203.0.113.10'))
    source = yaml.safe_load(calls[1][1])
    assert source['mirrors'] == existing['mirrors']
    assert source['configs']['other.internal'] == existing['configs']['other.internal']
    assert source['configs']['203.0.113.10:18444']['tls']['ca_file'] == '/etc/rancher/k3s/harbor_ca.crt'
    assert all('restart' not in args for args, _ in calls)


def test_check_is_offline_and_does_not_create_state(tmp_path, monkeypatch, capsys):
    import json
    import sys
    from teoria.entrypoints import k3d_remote_access as module
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('check executed a command'))
    monkeypatch.setattr(sys, 'argv', ['remote-access', '--root', str(tmp_path), '--address', '203.0.113.10', '--check'])
    module.main()
    assert json.loads(capsys.readouterr().out)['desired']['platform_port'] == 18443
    assert not (tmp_path / 'deploy').exists()


def test_configuration_data_cannot_execute_shell_and_pending_input_cannot_deploy(tmp_path):
    import json
    from teoria.entrypoints.k3d_remote_access import read_configuration, deployment_registry, configuration_text
    local = tmp_path / 'deploy/kubernetes/k3d/.local'
    local.mkdir(parents=True)
    path = local / 'remote_access.env'
    path.write_text('TEORIA_K3D_ADDRESS=$(touch /tmp/not-a-command)\n')
    with pytest.raises(ValueError):
        read_configuration(tmp_path)
    settings = external_addresses('203.0.113.10', 19443, 19444)
    path.write_text(configuration_text(settings))
    assert read_configuration(tmp_path)['platform_port'] == 19443
    assert read_configuration(tmp_path, platform_port=20443)['platform_port'] == 20443
    with pytest.raises(ValueError, match='Apply remote access'):
        deployment_registry(tmp_path)
    (local / 'remote_access').mkdir()
    (local / 'remote_access/config.json').write_text(json.dumps(settings))
    assert deployment_registry(tmp_path) == '203.0.113.10:19444'
    path.write_text(configuration_text(external_addresses('203.0.113.20')))
    with pytest.raises(ValueError, match='differs'):
        deployment_registry(tmp_path)
    path.unlink()
    assert read_configuration(tmp_path) == settings  # Legacy receipt migration.
    (local / 'remote_access/pending.json').write_text('{}')
    with pytest.raises(ValueError, match='pending'):
        deployment_registry(tmp_path)


def test_duplicate_configuration_keys_are_rejected(tmp_path):
    from teoria.entrypoints.k3d_remote_access import read_configuration
    config = tmp_path / 'input.env'
    config.write_text('TEORIA_K3D_ADDRESS=203.0.113.10\nTEORIA_K3D_ADDRESS=203.0.113.20\n')
    with pytest.raises(ValueError, match='duplicate'):
        read_configuration(tmp_path, config)


async def test_read_only_verifier_checks_public_origin_and_never_follows_auth_redirects(tmp_path, monkeypatch):
    import httpx
    import ssl
    from teoria.entrypoints.k3d_remote_access import verify_endpoints
    calls = []
    bad_realm = False
    def respond(request):
        calls.append(request)
        authenticated = bool(request.headers.get('Authorization'))
        path = request.url.path
        if path == '/v2/':
            realm = 'https://wrong.example/service/token' if bad_realm else 'https://203.0.113.10:18444/service/token'
            return httpx.Response(401, headers={'WWW-Authenticate':'Bearer realm="'+realm+'",service="harbor-registry"'})
        status = 401 if path in {'/admin-api/v1/admin/auth/session', '/mlflow/health'} and not authenticated else 200
        return httpx.Response(status)
    actual = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert isinstance(kwargs['verify'], ssl.SSLContext)
        return actual(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, 'AsyncClient', client)
    # Test system trust loading separately from the isolated, real TLS integration test.
    monkeypatch.setattr(ssl, 'create_default_context', lambda **kwargs: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    credentials = {'PREFECT_API_AUTH_STRING':'ops:synthetic', 'TEORIA_ADMIN_API_TOKEN':'synthetic-admin'}
    await verify_endpoints(external_addresses('203.0.113.10'), tmp_path/'ca.crt', credentials)
    assert all(request.method == 'GET' for request in calls)
    assert any(request.url.path.endswith('/image-registry/repositories') for request in calls)
    bad_realm = True
    with pytest.raises(RuntimeError, match='different public origin'):
        await verify_endpoints(external_addresses('203.0.113.10'), tmp_path/'ca.crt', credentials)


def test_empty_input_file_cannot_silently_disable_existing_remote_access(tmp_path):
    from teoria.entrypoints.k3d_remote_access import read_configuration
    path = tmp_path/'deploy/kubernetes/k3d/.local/remote_access.env'
    path.parent.mkdir(parents=True)
    path.write_text('# accidentally blank input\n')
    with pytest.raises(ValueError, match='ADDRESS'):
        read_configuration(tmp_path)


@pytest.mark.parametrize('socket_line,blocked', [
    ('0: 00000000:480B 00000000:0000 0A', True),   # 18443 on every IPv4 interface.
    ('0: 0100007F:480B 00000000:0000 0A', False),  # Loopback mapping can coexist.
    ('0: 00000000000000000000000000000000:480B 00000000:0000 0A', True),
])
def test_prepare_checks_ports_on_daemon_host_before_touching_installed_resources(tmp_path, monkeypatch, socket_line, blocked):
    access = DevelopmentAccess(tmp_path)
    calls = []
    monkeypatch.setattr(access, 'kubectl', lambda *a: 'k3d-teoria')
    monkeypatch.setattr(access, 'inspect', lambda name: None if name == 'teoria-k3d-remote-access' else {'State': {'Running': True}})
    def run(*args, body=None):
        calls.append(args)
        if args[:2] == ('docker', 'run'):
            assert '--network' in args and args[args.index('--network') + 1] == 'host'
            assert '--read-only' in args and '--pull=never' in args
            return socket_line
        return ''
    monkeypatch.setattr(access, 'run', run)
    expected = 'already used' if blocked else 'local Harbor chart'
    with pytest.raises(ValueError, match=expected):
        access.prepare(external_addresses('203.0.113.10'))
    assert not any('stop' in args or 'patch' in args for args in calls)
    assert not (tmp_path/'deploy').exists()


def test_shell_preview_needs_no_uv_docker_or_backend_environment(tmp_path):
    import json
    import os
    from pathlib import Path
    import shutil
    import subprocess
    root = Path(__file__).resolve().parents[3]
    wrapper = tmp_path/'deploy/kubernetes/k3d/remote_access.sh'
    module = tmp_path/'backend/src/teoria/entrypoints/k3d_remote_access.py'
    wrapper.parent.mkdir(parents=True)
    module.parent.mkdir(parents=True)
    shutil.copyfile(root/'deploy/kubernetes/k3d/remote_access.sh', wrapper)
    shutil.copyfile(root/'backend/src/teoria/entrypoints/k3d_remote_access.py', module)
    binaries = tmp_path/'bin'
    binaries.mkdir()
    for command in ('uv', 'docker', 'kubectl'):
        executable = binaries/command
        executable.write_text('#!/bin/sh\nexit 99\n')
        executable.chmod(0o755)
    result = subprocess.run(['bash', str(wrapper), '--address', '203.0.113.10', '--check'],
        env={**os.environ, 'PATH':str(binaries)+os.pathsep+os.environ['PATH']}, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['desired']['harbor_port'] == 18444
    assert not (tmp_path/'deploy/kubernetes/k3d/.local').exists()
