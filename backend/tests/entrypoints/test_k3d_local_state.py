"""Legacy local inputs are migrated without executing scripts or changing cluster data."""

import json
from pathlib import Path
import shutil
import ssl

import pytest

from teoria.entrypoints.k3d_local_state import (
    HOST_KEYS,
    local_settings,
    migrate,
    read_env,
)
from teoria.settings import Settings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    for key in (*HOST_KEYS, "TEORIA_K3D_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "repo"
    local = root / "deploy/kubernetes/k3d/.local"
    target = root / "deploy/kubernetes/envs/dev"
    local.mkdir(parents=True)
    shutil.copytree(
        ROOT / "deploy/kubernetes/envs/dev",
        target,
        ignore=shutil.ignore_patterns("*.env", "harbor_values.yaml"),
    )
    credentials = {
        "admin_token": "synthetic-private-token",
        "app_db": "secret:p@ss/word",
        "platform_db": "synthetic-platform",
        "prefect_db": "synthetic-prefect-db",
        "prefect_password": "synthetic-prefect",
        "minio_root_password": "synthetic-minio",
        "mlflow_db": "synthetic-mlflow",
        "controller_secret": "synthetic-controller",
        "workload_secret": "synthetic-workload",
        "harbor_admin": "synthetic-harbor",
        "harbor_key": "synthetic-harbor-key",
        "robots": {
            "model_reader": {
                "name": "synthetic-reader",
                "secret": "synthetic-reader-secret",
            }
        },
    }
    (local / "credentials.json").write_text(json.dumps(credentials))
    (local / "session.env").write_text(
        f"export TEORIA_K3D_DATA_DIR={tmp_path}/host-data\nexport KUBECONFIG={local}/kubeconfig\nexport TEORIA_K3D_HTTP_PORT=18080\nexport TEORIA_K3D_HTTPS_PORT=18443\n"
    )
    for name, content in [
        ("kubeconfig", "keep-kubeconfig"),
        ("harbor.crt", "public-cert\nline-two\n"),
        ("harbor.key", "private-key"),
        ("tls.crt", "public-platform"),
        ("tls.key", "private-platform"),
        ("harbor_values.yaml", "database:\n  password: private-harbor-db\n"),
        ("build_images.py", 'raise RuntimeError("never execute legacy script")'),
        ("run_validation.py", 'print("never execute")'),
        ("old.log", "private log"),
        ("validation_report.json", '{"result":"old"}'),
        ("harbor-1.19.4.tgz", "chart-cache"),
        ("model_validation_v1.tar", "model-cache"),
    ]:
        (local / name).write_text(content)
    return root, local, target


def test_migration_check_does_not_write_and_redacts_private_values(legacy):
    root, local, target = legacy
    before = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    report = migrate(root)
    after = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert before == after
    assert "synthetic-private-token" not in json.dumps(report)
    assert "credentials.json" in report["archived_files"]
    assert not (root / ".artifacts").exists()


def test_migration_keeps_runtime_material_and_copies_only_known_inputs(legacy):
    root, local, target = legacy
    (target / "secrets.env").write_text(
        (target / "secrets.env.example")
        .read_text()
        .replace(
            "TEORIA_ADMIN_API_TOKEN=CHANGE_ME",
            "TEORIA_ADMIN_API_TOKEN=operator-owned-token",
        )
    )
    (target / "connections.env").write_text(
        (target / "connections.env.example").read_text()
    )
    original = (local / "credentials.json").read_bytes()
    report = migrate(root, apply=True)
    platform = read_env(target / "secrets.env")
    assert platform["TEORIA_ADMIN_API_TOKEN"] == "operator-owned-token"
    assert "secret%3Ap%40ss%2Fword" in platform["TEORIA_APP_DATABASE_URL"]
    assert platform["PREFECT_API_AUTH_STRING"] == "teoria:synthetic-prefect"
    assert (
        platform["TEORIA_RUNTIME_API_TOKEN"] == "CHANGE_ME"
    )  # Never invent/reuse a privileged credential.
    assert (
        read_env(target / "harbor_secrets.env")["HARBOR_ADMIN_PASSWORD"]
        == "synthetic-harbor"
    )
    assert (
        read_env(target / "control.env")["TEORIA_MODEL_STORAGE_SECRET_KEY"]
        == "synthetic-controller"
    )
    assert "TEORIA_ADMIN_API_TOKEN" in report["preserved_keys"]["secrets"]
    assert "TEORIA_RUNTIME_API_TOKEN" in report["unresolved_placeholders"]["secrets"]
    assert (
        target / "harbor_values.yaml"
    ).read_text() == "database:\n  password: private-harbor-db\n"
    for name in ("kubeconfig", "harbor.crt", "harbor.key", "tls.crt", "tls.key"):
        assert (local / name).exists()
    assert not (local / "credentials.json").exists()
    assert not (local / "build_images.py").exists()
    assert (root / report["backup"] / "credentials.json").read_bytes() == original
    assert (local / "cache/charts/harbor-1.19.4.tgz").read_text() == "chart-cache"
    assert (local / "cache/images/model_validation_v1.tar").read_text() == "model-cache"
    assert read_env(target / "k3d.env")["TEORIA_K3D_HTTP_PORT"] == "18080"
    assert local_settings(root)["TEORIA_K3D_HTTPS_PORT"] == "18443"
    assert (target / "secrets.env").stat().st_mode & 0o777 == 0o600
    assert (target / "connections.env").stat().st_mode & 0o777 == 0o600
    assert (root / report["backup"]).stat().st_mode & 0o777 == 0o700
    for directory in (local / "cache", local / "cache/charts", local / "cache/images"):
        assert directory.stat().st_mode & 0o777 == 0o700
        assert directory.stat().st_uid == root.stat().st_uid
    again = migrate(root, apply=True)
    assert again["updated_files"] == []
    assert again["backup"] is None


def test_cache_conflict_prevents_any_input_change(legacy):
    root, local, target = legacy
    destination = local / "cache/charts/harbor-1.19.4.tgz"
    destination.parent.mkdir(parents=True)
    destination.write_text("other cache")
    with pytest.raises(ValueError, match="cache destination"):
        migrate(root, apply=True)
    assert not (target / "secrets.env").exists()
    assert (local / "credentials.json").exists()


def test_pending_access_recovery_prevents_local_migration(legacy):
    root, local, target = legacy
    (local / "remote_access").mkdir()
    (local / "remote_access/pending.json").write_text("{}")
    with pytest.raises(ValueError, match="Recover"):
        migrate(root, apply=True)
    assert not (target / "secrets.env").exists()


def test_host_input_is_data_and_shell_overrides_are_explicit(legacy, monkeypatch):
    root, local, target = legacy
    (target / "k3d.env").write_text("TEORIA_K3D_HTTP_PORT=19080\n")
    assert local_settings(root)["TEORIA_K3D_HTTP_PORT"] == "19080"
    monkeypatch.setenv("TEORIA_K3D_HTTP_PORT", "20080")
    assert local_settings(root)["TEORIA_K3D_HTTP_PORT"] == "20080"
    monkeypatch.delenv("TEORIA_K3D_HTTP_PORT")
    (target / "k3d.env").write_text("TEORIA_K3D_HTTP_PORT=$(touch /tmp/must-not-run)\n")
    with pytest.raises(ValueError):
        local_settings(root)
    monkeypatch.setenv("TEORIA_K3D_ENV_FILE", str(target / "absent.env"))
    with pytest.raises(ValueError, match="does not exist"):
        local_settings(root)


def test_registry_ca_env_round_trip_is_accepted_by_real_tls_context():
    certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
    assert certificates
    pem = ssl.DER_cert_to_PEM_cert(certificates[0])
    encoded = pem.replace("\n", r"\n")
    settings = Settings(image_registry_ca_pem=encoded)
    assert settings.image_registry_ca_pem == pem
    assert isinstance(
        ssl.create_default_context(cadata=settings.image_registry_ca_pem),
        ssl.SSLContext,
    )
