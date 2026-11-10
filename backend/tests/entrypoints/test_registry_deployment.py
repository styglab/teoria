"""Registry bootstrap is independent from platform application deployment."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_registry_bootstrap_uses_public_image_persistent_storage_and_no_platform_secrets():
    compose = yaml.safe_load(
        (ROOT / "deploy/compose/registry/compose.yaml").read_text()
    )
    assert set(compose["services"]) == {"registry"}
    registry = compose["services"]["registry"]
    assert registry["image"] == "registry:3.1.2"
    assert "depends_on" not in registry
    assert "registry-data:/var/lib/registry" in registry["volumes"]
    config = yaml.safe_load((ROOT / "deploy/compose/registry/config.yaml").read_text())
    assert config["auth"]["htpasswd"]["path"].endswith("htpasswd")
    assert config["http"]["tls"]["minimumtls"] == "tls1.2"
    assert config["storage"]["delete"]["enabled"] is False
    resources = list(
        yaml.safe_load_all((ROOT / "deploy/k3s/registry/registry.yaml").read_text())
    )
    deployment = next(r for r in resources if r["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    assert (
        deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    )
    ingress = next(r for r in resources if r["kind"] == "Ingress")
    assert ingress["spec"]["tls"][0]["secretName"] == "registry-tls"
    for r in resources:
        assert "teoria-secrets" not in str(r)


def test_k3s_accepts_custom_registry_before_cluster_access(tmp_path):
    # An invalid input must stop before invoking kubectl, including shell metacharacters.
    script = ROOT / "deploy/k3s/deploy.sh"
    marker = tmp_path / "unexpected"
    for prefix in (
        "https://registry.example.com/teoria",
        "registry.example.com/teoria;touch " + str(marker),
        "registry.example.com/../teoria",
    ):
        result = subprocess.run(
            ["bash", str(script), prefix, "a" * 40, "teoria.example.com"],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode != 0
        assert "Invalid image registry prefix" in result.stderr
    assert not marker.exists()
