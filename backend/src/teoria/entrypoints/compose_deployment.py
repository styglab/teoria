"""Compose lifecycle for Teoria modules; only Python's standard library is required."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4] / "deploy" / "compose"
MODULES = ("mlops", "semantic", "formatid")
BUILDER = "teoria"


def compose_command(modules: list[str], env_file: Path, project: str) -> list[str]:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--project-name",
        project,
        "-f",
        str(ROOT / "compose.yaml"),
    ]
    for module in MODULES:
        if module in modules:
            command += ["-f", str(ROOT / f"compose_{module}.yaml")]
    return command


def call(command: list[str], *, capture: bool = False, input: str | None = None) -> str:
    result = subprocess.run(
        command,
        input=input,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        check=True,
    )
    return result.stdout or ""


def write_state(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "config",
            "deploy",
            "start",
            "status",
            "stop",
            "down",
            "build",
            "cleanup",
        ),
    )
    choose = parser.add_mutually_exclusive_group()
    choose.add_argument(
        "--modules",
        help="comma-separated: mlops,semantic,formatid; core for common services only",
    )
    choose.add_argument("--all", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project-name", default="teoria")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="maintenance and readiness deadline in seconds",
    )
    parser.add_argument(
        "--apply", action="store_true", help="delete candidates printed by cleanup"
    )
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    project = args.project_name
    if not project or any(
        c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in project
    ):
        parser.error("Invalid project name")
    state_root = ROOT / ".state" / project
    readonly = args.action in {"config", "status"} or (
        args.action == "cleanup" and not args.apply
    )
    if not readonly:
        state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with nullcontext(None) if readonly else (state_root / "lock").open("w") as lock:
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        state_file = state_root / "deployment.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if args.all:
            modules = list(MODULES)
        elif args.modules is not None:
            modules = [] if args.modules == "core" else args.modules.split(",")
        else:
            modules = state.get("modules", [])
        if len(set(modules)) != len(modules) or set(modules) - set(MODULES):
            parser.error("Choose modules from mlops,semantic,formatid, or core")
        modules = [m for m in MODULES if m in modules]
        if (
            args.action in {"start", "stop", "down", "status"}
            and state
            and modules != state["modules"]
        ):
            parser.error(
                "Use deploy to change modules; lifecycle commands use the saved selection"
            )
        command = compose_command(modules, args.env_file.resolve(), project)
        # Render internally, never print expanded secrets to the terminal or log files.
        config = json.loads(
            call(
                command + ["--profile", "*", "config", "--format", "json"],
                capture=True,
            )
        )
        config_checksum = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()
        services = config["services"]
        assessment_enabled = (
            "semantic" in modules
            and services["admin-api"]
            .get("environment", {})
            .get("TEORIA_ASSESSMENT_ENABLED")
            == "true"
        )
        if assessment_enabled:
            command += ["--profile", "assessment"]
        persistent = [
            name
            for name, service in services.items()
            if not service.get("profiles")
            or (name == "metadata-assessment-worker" and assessment_enabled)
        ]
        workers = [n for n in persistent if "worker" in n]
        infrastructure = [
            n
            for n in (
                "postgres",
                "platform-postgres",
                "prefect-redis",
                "minio",
                "runtime-redis",
                "openmetadata-search",
            )
            if n in persistent
        ]
        application = [n for n in persistent if n not in infrastructure + workers]
        timeout = str(args.timeout)

        if args.action == "deploy":
            required = [("minio", "MINIO_ROOT_USER"), ("minio", "MINIO_ROOT_PASSWORD")]
            if "mlops" in modules:
                required += [
                    ("mlflow-postgres-init", "TEORIA_MLFLOW_DB_PASSWORD"),
                    ("demo-inference", "TEORIA_DEMO_INFERENCE_TOKEN"),
                ]
            if "formatid" in modules:
                required += [
                    ("minio-init", "SPECIFICATION_WORKER_PASSWORD"),
                    ("minio-init", "SPECIFICATION_API_PASSWORD"),
                ]
            if "semantic" in modules:
                required += [
                    ("prefect-law-worker", "TEORIA_CONNECTOR_MOLEG_LAW_API_KEY")
                ]
            missing = [
                f"{service}.{key}"
                for service, key in required
                if not services[service].get("environment", {}).get(key)
            ]
            if missing:
                raise RuntimeError(
                    "Configure credentials before deployment: " + ", ".join(missing)
                )

        def up(names: list[str]) -> None:
            if names:
                call(
                    command
                    + [
                        "up",
                        "-d",
                        "--no-build",
                        "--no-deps",
                        "--wait",
                        "--wait-timeout",
                        timeout,
                        *names,
                    ]
                )

        def job(name: str, extra: list[str] | None = None) -> None:
            image = services[name]["image"]
            present = subprocess.run(
                ["docker", "image", "inspect", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if present.returncode:
                raise RuntimeError(
                    f"Missing image for {name}; run build for the selected modules first"
                )
            log_root = state_root / "logs"
            log_root.mkdir(exist_ok=True, mode=0o700)
            log = log_root / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{name}.log"
            print(f"Initialization: {name} (log: {log})", flush=True)
            with log.open("w") as stream:
                log.chmod(0o600)
                result = subprocess.run(
                    command
                    + [
                        "run",
                        "--rm",
                        "--no-deps",
                        "--pull",
                        "never",
                        "-T",
                        name,
                        *(extra or []),
                    ],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            if result.returncode:
                raise RuntimeError(f"Initialization failed: {name}; inspect {log}")

        def maintenance(action: str, saved: dict) -> dict:
            output = call(
                command
                + [
                    "exec",
                    "-T",
                    "admin-api",
                    "python",
                    "-m",
                    "teoria.integrations.prefect.maintenance",
                    action,
                ],
                capture=True,
                input=json.dumps(saved),
            )
            return json.loads(output)

        def quiesce() -> None:
            running = call(
                command + ["--profile", "*", "ps", "--status", "running", "--services"],
                capture=True,
            ).split()
            if "admin-api" not in running or "prefect-server" not in running:
                if any("worker" in n for n in running):
                    raise RuntimeError(
                        "Worker is running but Admin/Prefect is unavailable; restore management before stopping"
                    )
                return
            # Preserve the first snapshot through retries and failed deploys.
            if "maintenance" not in state:
                state["maintenance"] = maintenance(
                    "snapshot", state.get("inactive_maintenance", {})
                )
                state.setdefault("modules", modules)
                write_state(state_file, state)
            maintenance("pause", state["maintenance"])
            call(command + ["stop", "--timeout", "60", "nginx"])
            if "metadata-assessment-worker" in running:
                # SIGTERM stops new claims; the current diagnosis can finish within its 8-minute budget.
                call(command + ["stop", "metadata-assessment-worker"])
            deadline = time.monotonic() + args.timeout
            while maintenance("active", state["maintenance"])["active"]:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Active/paused Flows remain; pools/schedules stay paused. Finish them before retrying"
                    )
                time.sleep(2)
            # Stop request acceptance and process workers before touching dependencies.
            call(command + ["stop", "--timeout", "60", "nginx", "admin-api", *workers])
            # Keep databases/search alive until API servers and control services exit.
            call(command + ["stop", "--timeout", "60", *application])

        def verify() -> None:
            expected = {name: name in modules for name in MODULES}
            call(
                command
                + [
                    "exec",
                    "-T",
                    "admin-api",
                    "python",
                    "-m",
                    "teoria.entrypoints.deployment_check",
                    json.dumps(expected),
                ]
            )

        def image_ids() -> list[str]:
            tags = sorted({s["image"] for s in services.values() if "image" in s})
            identifiers = set()
            for tag in tags:
                result = subprocess.run(
                    ["docker", "image", "inspect", tag], capture_output=True, text=True
                )
                if result.returncode == 0:
                    identifiers.add(json.loads(result.stdout)[0]["Id"])
            return sorted(identifiers)

        def cleanup(apply: bool) -> None:
            protected = set(state.get("images", []) + state.get("previous_images", []))
            selected_repositories = {
                service["image"].rsplit(":", 1)[0]
                for service in services.values()
                if service.get("image")
            }
            for saved_file in (ROOT / ".state").glob("*/deployment.json"):
                saved = json.loads(saved_file.read_text())
                protected.update(
                    saved.get("images", []) + saved.get("previous_images", [])
                )
            containers = call(["docker", "ps", "-aq"], capture=True).split()
            if containers:
                protected.update(
                    c["Image"]
                    for c in json.loads(
                        call(["docker", "inspect", *containers], capture=True)
                    )
                )
            candidates = call(
                [
                    "docker",
                    "image",
                    "ls",
                    "--all",
                    "-q",
                    "--filter",
                    "label=io.teoria.project=teoria",
                ],
                capture=True,
            ).split()
            for identifier in dict.fromkeys(candidates):
                info = json.loads(
                    call(["docker", "image", "inspect", identifier], capture=True)
                )[0]
                # A core-only deployment must not discard staged images for other modules.
                if info.get("RepoTags") and all(
                    tag.rsplit(":", 1)[0] not in selected_repositories
                    for tag in info["RepoTags"]
                ):
                    continue
                if info["Id"] in protected:
                    continue
                print(
                    "Unused Teoria image:",
                    info["Id"],
                    ", ".join(info.get("RepoTags") or []),
                )
                if apply:
                    call(
                        [
                            "docker",
                            "image",
                            "rm",
                            *(info.get("RepoTags") or [info["Id"]]),
                        ]
                    )
            print(
                "Cleanup complete"
                if apply
                else "Preview only; use cleanup --apply to delete"
            )

        if args.action == "config":
            print(
                json.dumps(
                    {
                        "modules": modules,
                        "services": persistent,
                        "jobs": [
                            n
                            for n, s in services.items()
                            if "jobs" in s.get("profiles", [])
                        ],
                    },
                    indent=2,
                )
            )
        elif args.action == "status":
            call(command + ["--profile", "*", "ps", "-a"])
        elif args.action == "build":
            builders = call(
                ["docker", "buildx", "ls", "--format", "{{.Name}}"], capture=True
            ).split()
            if BUILDER not in builders:
                call(
                    [
                        "docker",
                        "buildx",
                        "create",
                        "--name",
                        BUILDER,
                        "--driver",
                        "docker-container",
                        "--driver-opt",
                        "image=moby/buildkit:v0.30.0",
                        "--buildkitd-config",
                        str(ROOT / "buildkitd.toml"),
                    ]
                )
            build_services = []
            seen_images = set()
            for name, service in services.items():
                if (
                    not service.get("build")
                    or name in {"platform-check", "pipelines-check"}
                    or (name == "metadata-assessment-worker" and not assessment_enabled)
                    or service["image"] in seen_images
                ):
                    continue
                seen_images.add(service["image"])
                build_services.append(name)
            call(
                command
                + ["--profile", "jobs", "build", "--builder", BUILDER, *build_services]
            )
            call(
                [
                    "docker",
                    "buildx",
                    "prune",
                    "--builder",
                    BUILDER,
                    "--force",
                    "--filter",
                    "until=168h",
                    "--keep-storage",
                    "20GB",
                ]
            )
        elif args.action in {"stop", "down"}:
            quiesce()
            call(command + ["--profile", "*", args.action, "--timeout", "60"])
        elif args.action == "start":
            if not state.get("prepared"):
                raise RuntimeError("Run deploy once to initialize this configuration")
            if state.get("config_checksum") != config_checksum:
                raise RuntimeError("Configuration changed; use deploy instead of start")
            up(infrastructure)
            up(application)
            verify()
            up(workers)
            if state.get("maintenance"):
                state["inactive_maintenance"] = maintenance(
                    "resume", state["maintenance"]
                )
                del state["maintenance"]
                write_state(state_file, state)
        elif args.action == "deploy":
            if state and state.get("modules") != modules:
                # Drain using the old module configuration before changing selection.
                old = compose_command(
                    state["modules"], args.env_file.resolve(), project
                )
                if call(old + ["ps", "--all", "--services"], capture=True).strip():
                    raise RuntimeError(
                        "Changing modules requires down with the saved configuration first; then deploy with --modules"
                    )
            quiesce()
            state.update(modules=modules, prepared=False)
            write_state(state_file, state)
            up(infrastructure)
            for name in (
                "postgres-init",
                "platform-postgres-init",
                "postgres-migrate",
                "app-postgres-migrate",
                "opa-bundle-build",
            ):
                job(name)
            if "mlops" in modules:
                job("mlflow-postgres-init")
                job("model-storage-init")
            if "formatid" in modules:
                job("minio-init")
            if "semantic" in modules:
                job("postgres-metadata-grants")
                job("openmetadata-migrate")
                job("runtime-artifact-check")
            up(application)
            # Existing DBs may contain schedules for modules omitted from this installation.
            # Snapshot them before registration and keep disabled module pools paused.
            retained = state.get("maintenance", state.get("inactive_maintenance", {}))
            state["maintenance"] = maintenance("snapshot", retained)
            write_state(state_file, state)
            maintenance("pause", state["maintenance"])
            if maintenance("active", state["maintenance"])["active"]:
                raise RuntimeError(
                    "Existing active Flows remain; inspect Prefect before starting workers"
                )
            for module, names in {
                "mlops": ["model-register"],
                "semantic": ["prefect-law-deploy", "prefect-metadata-deploy"],
                "formatid": ["prefect-deploy"],
            }.items():
                if module in modules:
                    for name in names:
                        job(name)
            verify()
            up(workers)
            remaining = state.get("inactive_maintenance", {})
            if state.get("maintenance"):
                remaining = maintenance("resume", state["maintenance"])
            current = image_ids()
            state = {
                "modules": modules,
                "prepared": True,
                "config_checksum": config_checksum,
                "images": current,
                "previous_images": state.get("previous_images", [])
                if current == state.get("images")
                else state.get("images", []),
                "inactive_maintenance": remaining,
            }
            write_state(state_file, state)
            print(
                "Deployment readiness checks passed; saved module selection and image references"
            )
            cleanup(True)
        elif args.action == "cleanup":
            if args.apply and not state.get("prepared"):
                raise RuntimeError(
                    "A successful saved deployment is required to protect current/rollback images"
                )
            cleanup(args.apply)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(
            str(error)
            if isinstance(error, RuntimeError)
            else "Docker command failed; deployment stopped",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
