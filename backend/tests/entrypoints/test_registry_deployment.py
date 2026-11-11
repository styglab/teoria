"""Model Registry belongs to the optional platform MLOps deployment."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_integrated_registry_uses_public_image_persistent_storage_and_no_platform_secrets():
    compose = yaml.safe_load(
        (ROOT / "deploy/compose/compose_mlops.yaml").read_text()
    )
    core = yaml.safe_load((ROOT / "deploy/compose/compose.yaml").read_text())
    assert "image-registry" not in core["services"]
    registry = compose["services"]["image-registry"]
    assert registry["image"] == "registry:3.1.2"
    assert "depends_on" not in registry
    assert "registry-data:/var/lib/registry" in registry["volumes"]
    config = yaml.safe_load((ROOT / "deploy/compose/registry/config.yaml").read_text())
    assert config["auth"]["htpasswd"]["path"].endswith("htpasswd")
    assert "tls" not in config["http"]
    assert config["http"]["relativeurls"] is True
    assert "ports" not in registry
    assert not any(v.get("target", "").endswith(("tls.crt", "tls.key")) for v in registry["volumes"] if isinstance(v, dict))
    assert config["storage"]["delete"]["enabled"] is False
    resources = list(
        yaml.safe_load_all((ROOT / "deploy/kubernetes/base/mlops/registry.yaml").read_text())
    )
    deployment = next(r for r in resources if r["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    assert (
        deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    )
    ingress = yaml.safe_load((ROOT / "deploy/kubernetes/overlays/k3s/mlops/registry_ingress.yaml").read_text())
    assert ingress["spec"]["tls"][0]["secretName"] == "teoria-tls"
    for r in resources:
        assert "teoria-secrets" not in str(r)


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
         "teoria.example.com", "--overlay", "k3s", "--with-model-registry", "https://invalid.example"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Invalid model Registry hostname" in result.stderr
