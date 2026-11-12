"""The platform connects to an independently managed image Registry."""

import subprocess
from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_platform_deployments_do_not_install_a_registry():
    assert not any((ROOT / 'deploy/kubernetes/base').rglob('registry.yaml'))
    assert 'location /v2/' not in (ROOT / 'deploy/kubernetes/base/teoria/web_proxy/default.conf.template').read_text()


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
        'teoria.example.com', '--overlay', 'k3s', '--model-registry-host', 'registry.example.com',
        '--model-registry-url', origin,
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Invalid model Registry origin' in result.stderr


def test_docker_context_excludes_private_deployment_state_and_keeps_parser(tmp_path):
    pytest.importorskip('docker')
    from docker.utils.build import exclude_paths
    samples = {
        'deploy/kubernetes/k3d/.local/secrets.env': False,
        'deploy/kubernetes/k3d/.local/cached_model.tar': False,
        'deploy/kubernetes/k3d/.local/kubeconfig': False,
        'deploy/kubernetes/.release_example/kustomization.yaml': False,
        'deploy/kubernetes/private.env': False,
        'deploy/kubernetes/private.key': False,
        'deploy/kubernetes/kubeconfig': False,
        'backend/src/teoria/settings.py': True,
        'archive/kory_parser/src/kory_parser/__init__.py': True,
        'deploy/kubernetes/specification.env.example': True,
    }
    for name in samples:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic input')
    included = set(exclude_paths(str(tmp_path), (ROOT / '.dockerignore').read_text().splitlines(),
                                dockerfile='backend/Dockerfile'))
    for name, expected in samples.items():
        assert (name in included) is expected, name
