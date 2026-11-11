"""The platform connects to an independently managed image Registry."""

import subprocess
from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_platform_deployments_do_not_install_a_registry():
    for filename in ('compose.yaml', 'compose_mlops.yaml'):
        compose = yaml.safe_load((ROOT / 'deploy/compose' / filename).read_text())
        assert 'image-registry' not in compose['services']
        assert 'registry-data' not in compose.get('volumes', {})
    assert not (ROOT / 'deploy/kubernetes/base/mlops/registry.yaml').exists()
    assert 'location /v2/' not in (ROOT / 'deploy/compose/nginx/nginx.conf').read_text()


def test_k3s_accepts_custom_registry_before_cluster_access(tmp_path):
    # An invalid input must stop before invoking kubectl, including shell metacharacters.
    script = ROOT / "deploy/kubernetes/deploy.sh"
    marker = tmp_path / "unexpected"
    for prefix in (
        "https://registry.example.com/teoria",
        "registry.example.com/teoria;touch " + str(marker),
        "registry.example.com/../teoria",
    ):
        result = subprocess.run(
            ["bash", str(script), prefix, "a" * 40, "teoria.example.com", "--overlay", "k3s"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0
        assert "Invalid image registry prefix" in result.stderr
    assert not marker.exists()


def test_k3s_rejects_invalid_model_registry_before_cluster_access():
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/kubernetes/deploy.sh"), "ghcr.io/example", "a" * 40,
         "teoria.example.com", "--overlay", "k3s", "--model-registry-host", "https://invalid.example"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Invalid model Registry host" in result.stderr


@pytest.mark.parametrize('origin', [
    'file:///tmp/registry',
    'https://user:synthetic@registry.example.com',
    'https://registry.example.com/private?token=synthetic',
    'https://registry.example.com:99999',
])
def test_external_registry_origin_rejects_credentials_and_non_origin_urls(origin):
    result = subprocess.run([
        'bash', str(ROOT / 'deploy/kubernetes/deploy.sh'), 'ghcr.io/example', 'a' * 40,
        'teoria.example.com', '--modules', 'mlops', '--model-registry-host', 'registry.example.com',
        '--model-registry-url', origin,
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Invalid model Registry origin' in result.stderr
