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
        if args[-2:] == ('cat', '/etc/rancher/k3s/registries.yaml'):
            return yaml.safe_dump(existing)
        return ''
    monkeypatch.setattr(access, 'run', run)
    access.restore_node(external_addresses('203.0.113.10'))
    source = yaml.safe_load(calls[1][1])
    assert source['mirrors'] == existing['mirrors']
    assert source['configs']['other.internal'] == existing['configs']['other.internal']
    assert source['configs']['203.0.113.10:18444']['tls']['ca_file'] == '/etc/rancher/k3s/harbor_ca.crt'
    assert all('restart' not in args for args, _ in calls)
