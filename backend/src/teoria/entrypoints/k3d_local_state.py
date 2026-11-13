"""Read k3d host inputs and migrate legacy local setup artifacts without cluster access."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
from urllib.parse import quote, urlsplit

HOST_KEYS = (
    "TEORIA_K3D_DATA_DIR",
    "TEORIA_K3D_KUBECONFIG",
    "TEORIA_K3D_API_SERVER",
    "TEORIA_K3D_HTTP_PORT",
    "TEORIA_K3D_HTTPS_PORT",
    "TEORIA_K3D_REVISION",
)
LEGACY_SCRIPTS = (
    "build_images.py",
    "check_lifecycle.py",
    "check_public_access.py",
    "configure_access.py",
    "provision_harbor.py",
    "provision_platform.py",
    "provision_storage.py",
    "push_model.py",
    "push_platform.py",
    "run_component_validation.py",
    "run_validation.py",
)
REPORTS = (
    "validation_report.json",
    "public_validation_report.json",
    "component_validation_report.json",
    "lifecycle_baseline.json",
)


def read_env(path):
    """Read literal env input, including legacy shell quoting; never execute it."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip().removeprefix("export ")
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if (
            not separator
            or key in result
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
        ):
            raise ValueError("Invalid or duplicate env input key")
        # Kubernetes --from-env-file uses literal values. Only legacy session.env uses shell quotes.
        if path.name == "session.env":
            tokens = shlex.split(value)
            if len(tokens) != 1:
                raise ValueError("Legacy session value must be one literal token")
            value = tokens[0]
        result[key] = value
    return result


def local_settings(root):
    configured = Path(
        os.environ.get(
            "TEORIA_K3D_ENV_FILE", root / "deploy/kubernetes/envs/dev/k3d.env"
        )
    )
    if os.environ.get("TEORIA_K3D_ENV_FILE") and not configured.exists():
        raise ValueError("Explicit k3d host input file does not exist")
    legacy = root / "deploy/kubernetes/k3d/.local/session.env"
    values = read_env(configured if configured.exists() else legacy)
    if "KUBECONFIG" in values:
        values["TEORIA_K3D_KUBECONFIG"] = values.pop("KUBECONFIG")
    if set(values) - set(HOST_KEYS):
        raise ValueError("Unknown k3d host input key")
    for key in HOST_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    for key, value in values.items():
        if "\n" in value or "\r" in value or "$" in value or "`" in value:
            raise ValueError("k3d host inputs must be literal values")
        if not value:
            continue
        if key.endswith("_DIR") or key.endswith("_KUBECONFIG"):
            if not Path(value).is_absolute() or ":" in value:
                raise ValueError("k3d host paths must be absolute paths without colons")
        elif key.endswith("_PORT"):
            if not value.isdecimal() or not 1024 <= int(value) <= 65535:
                raise ValueError("k3d host ports must be unprivileged TCP ports")
        elif key.endswith("_REVISION") and not re.fullmatch("[a-f0-9]{40}", value):
            raise ValueError("k3d image revision must be a full commit SHA")
        elif key.endswith("_API_SERVER"):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("k3d API server requires an HTTPS origin")
            if parsed.port == 0:
                raise ValueError("Invalid k3d API server port")
    return {key: values.get(key, "") for key in HOST_KEYS}


def write_private(path, content, owner):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            temporary.chmod(0o600)
            stream.write(content.encode())
            stream.flush()
            os.fsync(stream.fileno())
            if os.geteuid() == 0:
                os.chown(temporary, owner.st_uid, owner.st_gid)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def legacy_inputs(local):
    """Explicit compatibility mapping for the original MLOps-only development installation."""
    path = local / "credentials.json"
    c = json.loads(path.read_text()) if path.exists() else {}

    def dsn(role, key, database, prefix="postgresql", host="platform-postgres"):
        return (
            f"{prefix}://{role}:{quote(c[key], safe='')}@{host}:5432/{database}"
            if c.get(key)
            else None
        )

    platform = {
        "TEORIA_ADMIN_API_TOKEN": c.get("admin_token"),
        "TEORIA_LOCAL_PLATFORM_DB_PASSWORD": c.get("platform_db"),
        "TEORIA_LOCAL_APP_DB_PASSWORD": c.get("app_db"),
        "TEORIA_LOCAL_PREFECT_DB_PASSWORD": c.get("prefect_db"),
        "TEORIA_APP_DATABASE_URL": dsn("teoria_app", "app_db", "teoria_app"),
        "PREFECT_API_DATABASE_CONNECTION_URL": dsn(
            "prefect", "prefect_db", "prefect", "postgresql+asyncpg"
        ),
        "PREFECT_API_AUTH_STRING": "teoria:" + c["prefect_password"]
        if c.get("prefect_password")
        else None,
        "TEORIA_MINIO_ROOT_USER": "teoria-minio" if c else None,
        "TEORIA_MINIO_ROOT_PASSWORD": c.get("minio_root_password"),
    }
    access_path = local / "remote_access/config.json"
    access = json.loads(access_path.read_text()) if access_path.exists() else {}
    harbor = access.get("harbor_url", "https://harbor.teoria.localhost")
    reader = c.get("robots", {}).get("model_reader", {})
    if reader:
        platform.update(
            TEORIA_IMAGE_REGISTRY_PROVIDER="harbor",
            TEORIA_IMAGE_REGISTRY_PROJECT="models",
            TEORIA_IMAGE_REGISTRY_URL=harbor,
            TEORIA_IMAGE_REGISTRY_PUBLIC_HOST=urlsplit(harbor).netloc,
            TEORIA_IMAGE_REGISTRY_USERNAME=reader["name"],
            TEORIA_IMAGE_REGISTRY_PASSWORD=reader["secret"],
        )
        if (local / "harbor.crt").exists():
            platform["TEORIA_IMAGE_REGISTRY_CA_PEM"] = (
                (local / "harbor.crt").read_text().rstrip().replace("\n", r"\n")
            )
    registries = ",".join(
        dict.fromkeys(["harbor.teoria.localhost", urlsplit(harbor).netloc])
    )
    control = {
        "TEORIA_MLFLOW_DB_PASSWORD": c.get("mlflow_db"),
        "MLFLOW_BACKEND_STORE_URI": dsn(
            "mlflow", "mlflow_db", "mlflow", "postgresql+psycopg2"
        ),
        "TEORIA_MODEL_ALLOWED_REGISTRIES": registries if c else None,
        "TEORIA_MODEL_STORAGE_ACCESS_KEY": "teoria-controller"
        if c.get("controller_secret")
        else None,
        "TEORIA_MODEL_STORAGE_SECRET_KEY": c.get("controller_secret"),
    }
    workload = {
        "AWS_ACCESS_KEY_ID": "teoria-workload" if c.get("workload_secret") else None,
        "AWS_SECRET_ACCESS_KEY": c.get("workload_secret"),
    }
    return {
        "secrets": platform,
        "control": control,
        "workload": workload,
        "harbor_secrets": {
            "HARBOR_ADMIN_PASSWORD": c.get("harbor_admin"),
            "secretKey": c.get("harbor_key"),
        },
    }, access


def merge_input(path, template, additions):
    """Fill placeholders only. Existing non-placeholder operator inputs always win."""
    original = path.read_text() if path.exists() else template.read_text()
    merged, conflicts = [], []
    for line in original.splitlines():
        key, separator, value = line.partition("=")
        candidate = additions.get(key)
        if separator and not line.lstrip().startswith("#") and candidate is not None:
            if not value or "CHANGE_ME" in value:
                if "\n" in candidate or "\r" in candidate:
                    raise ValueError("Multiline env values must be encoded explicitly")
                line = key + "=" + candidate
            elif value != candidate:
                conflicts.append(key)
        merged.append(line)
    return "\n".join(merged) + "\n", conflicts


def migrate(root, *, apply=False):
    local = root / "deploy/kubernetes/k3d/.local"
    target = root / "deploy/kubernetes/envs/dev"
    if (local / "remote_access/pending.json").exists():
        raise ValueError(
            "Recover the pending remote access change before migrating local files"
        )
    candidates, access = legacy_inputs(local)
    changes, conflicts = {}, {}
    for name in (
        "connections",
        "secrets",
        "control",
        "workload",
        "specification",
        "harbor_secrets",
    ):
        path = target / (name + ".env")
        changes[path], conflicts[name] = merge_input(
            path, target / (name + ".env.example"), candidates.get(name, {})
        )
    settings = local_settings(root)
    host_path = target / "k3d.env"
    if not host_path.exists():
        changes[host_path] = (
            "\n".join(key + "=" + value for key, value in settings.items()) + "\n"
        )
    remote = local / "remote_access.env"
    if access and not remote.exists():
        # Values are public, but validate before retaining them as the new authoritative input.
        from teoria.entrypoints.k3d_remote_access import (
            external_addresses,
            configuration_text,
        )

        normalized = external_addresses(
            access["address"], access["platform_port"], access["harbor_port"]
        )
        changes[remote] = configuration_text(normalized)
    harbor = local / "harbor_values.yaml"
    if harbor.exists() and not (target / "harbor_values.yaml").exists():
        changes[target / "harbor_values.yaml"] = harbor.read_text()
    changes = {
        path: content
        for path, content in changes.items()
        if not path.exists() or path.read_text() != content
    }
    archive = (
        root
        / ".artifacts/k3d_legacy"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    legacy = [
        local / name
        for name in (
            *LEGACY_SCRIPTS,
            *REPORTS,
            "credentials.json",
            "session.env",
            "harbor_values.yaml",
        )
        if (local / name).exists()
    ]
    legacy += list(local.glob("*.log"))
    if (local / "build_logs").exists():
        legacy.append(local / "build_logs")
    cache = [
        path
        for path in local.iterdir()
        if path.is_file()
        and (path.suffix == ".tgz" or path.name.startswith("model_validation_v1.tar"))
    ]
    report = {
        "mode": "apply" if apply else "check",
        "updated_files": [str(p.relative_to(root)) for p in changes],
        "preserved_keys": {k: v for k, v in conflicts.items() if v},
        "archived_files": [p.name for p in legacy],
        "cached_files": [p.name for p in cache],
        "backup": str(archive.relative_to(root)),
        "unresolved_placeholders": {},
        "note": "No Kubernetes/Docker changes. Unavailable new credentials remain unset/placeholders.",
    }
    # Report keys only; never include the actual replacement values.
    for name in ("secrets", "control", "workload", "specification", "harbor_secrets"):
        path = target / (name + ".env")
        content = changes.get(path, path.read_text() if path.exists() else "")
        report["unresolved_placeholders"][name] = [
            line.partition("=")[0]
            for line in content.splitlines()
            if not line.lstrip().startswith("#")
            and "=" in line
            and "CHANGE_ME" in line.partition("=")[2]
        ]
    for path in changes:
        if path.is_symlink():
            raise ValueError("Migrate explicit env files instead of replacing symlinks")
    for path in cache:
        destination = (
            local
            / "cache"
            / ("charts" if path.suffix == ".tgz" else "images")
            / path.name
        )
        if destination.exists():
            raise ValueError("A cache destination already exists; no input was changed")
    if not apply:
        return report
    owner = root.stat()
    if not changes and not legacy and not cache:
        report["backup"] = None
        return report
    archive.mkdir(parents=True, mode=0o700)
    write_private(
        archive / "migration_report.json",
        json.dumps({**report, "status": "prepared"}, indent=2) + "\n",
        owner,
    )
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    # Back up every overwritten input first. Original legacy files are moved only after input writes complete.
    for path, content in changes.items():
        if path.exists():
            backup = archive / "previous_inputs" / path.relative_to(root)
            write_private(backup, path.read_text(), owner)
        write_private(path, content, owner)
    for path in legacy:
        path.rename(archive / path.name)
    for path in cache:
        destination = (
            local
            / "cache"
            / ("charts" if path.suffix == ".tgz" else "images")
            / path.name
        )
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            raise ValueError(
                "A cache destination already exists; original inputs/backups were retained"
            )
        path.rename(destination)
    cache_directories = [local / "cache", *(local / "cache").glob("*")] if cache else []
    input_files = list(target.glob("*.env"))
    if (target / "harbor_values.yaml").exists():
        input_files.append(target / "harbor_values.yaml")
    for path in [
        *input_files,
        archive.parent,
        archive,
        *archive.rglob("*"),
        target,
        *cache_directories,
    ]:
        if not path.is_symlink():
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
            if os.geteuid() == 0:
                os.chown(path, owner.st_uid, owner.st_gid)
    write_private(
        archive / "migration_report.json",
        json.dumps({**report, "status": "complete"}, indent=2) + "\n",
        owner,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["settings", "migrate"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "settings":
            print("\n".join(local_settings(args.root).values()))
        else:
            if not args.apply:
                print(json.dumps(migrate(args.root), indent=2))
                return
            # Use the same operation lock as deployment and remote access changes.
            import fcntl

            with (Path.home() / ".teoria-deploy.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                print(json.dumps(migrate(args.root, apply=args.apply), indent=2))
    except Exception as exc:
        parser.exit(
            1,
            "Local state operation failed ("
            + type(exc).__name__
            + "); private values were not logged.\n",
        )


if __name__ == "__main__":
    main()
