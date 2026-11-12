"""Offline validation of the independently installed Harbor chart and k3d endpoints."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
HARBOR = ROOT / 'deploy/kubernetes/harbor'


@pytest.mark.parametrize('overlay', ['k3d', 'k3s', 'generic'])
def test_harbor_chart_keeps_storage_and_direct_registry_ingress(tmp_path, overlay):
    chart = os.getenv('TEORIA_TEST_HARBOR_CHART')
    if not chart or not shutil.which('helm'):
        pytest.skip('Set TEORIA_TEST_HARBOR_CHART to the pinned local chart archive; helm required')
    private = tmp_path / 'values.yaml'
    private.write_text('database:\n  internal:\n    password: synthetic-test-password\n')
    result = subprocess.run(['bash', str(HARBOR / 'deploy.sh'), '--overlay', overlay,
                             '--chart', chart, '--values', str(private), '--render'],
                            env={**os.environ, 'KUBECONFIG': str(tmp_path / 'absent')},
                            text=True, capture_output=True, check=True)
    resources = [r for r in yaml.safe_load_all(result.stdout) if r]
    ingress = next(r for r in resources if r['kind'] == 'Ingress')
    host = 'harbor.teoria.localhost' if overlay == 'k3d' else 'harbor.example.com'
    assert ingress['spec']['rules'][0]['host'] == host
    assert any(p['path'].startswith('/v2') for p in ingress['spec']['rules'][0]['http']['paths'])
    claims = [r for r in resources if r['kind'] == 'PersistentVolumeClaim']
    assert claims
    assert all(c['metadata']['annotations']['helm.sh/resource-policy'] == 'keep' for c in claims)
    if overlay != 'generic':
        expected = 'teoria-local' if overlay == 'k3d' else 'local-path'
        assert all(c['spec']['storageClassName'] == expected for c in claims)
    assert not any('trivy' in r['metadata']['name'] for r in resources)


def test_wrong_chart_is_rejected_before_helm_or_cluster_access(tmp_path):
    chart = tmp_path / 'wrong.tgz'
    chart.write_bytes(b'not-the-approved-chart')
    values = tmp_path / 'private.yaml'
    values.write_text('{}')
    result = subprocess.run(['bash', str(HARBOR / 'deploy.sh'), '--chart', str(chart), '--values', str(values)],
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert 'checksum mismatch' in result.stderr


def test_k3d_registry_name_uses_tls_without_a_second_registry():
    config = yaml.safe_load((ROOT / 'deploy/kubernetes/k3d/cluster.yaml').read_text())
    assert 'create' not in config['registries']
    settings = yaml.safe_load(config['registries']['config'])
    assert settings['configs']['harbor.teoria.localhost']['tls']['ca_file'] == '/etc/rancher/k3s/harbor_ca.crt'
    assert any(p['port'] == '127.0.0.1:443:443' for p in config['ports'])
