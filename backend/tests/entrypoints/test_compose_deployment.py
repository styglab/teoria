"""Exercise lifecycle ordering and failure boundaries without starting containers."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from teoria.entrypoints import compose_deployment as deployment


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.calls = []
        self.jobs = []
        self.fail_job = None
        self.fail_verify = False
        self.services = {
            n: {"image": "teoria-test:latest"}
            for n in (
                "postgres",
                "platform-postgres",
                "minio",
                "admin-api",
                "nginx",
                "prefect-server",
                "prefect-worker",
            )
        }
        self.services["minio"]["environment"] = {
            "MINIO_ROOT_USER": "synthetic",
            "MINIO_ROOT_PASSWORD": "synthetic",
        }
        for name in (
            "postgres-init",
            "platform-postgres-init",
            "postgres-migrate",
            "app-postgres-migrate",
            "opa-bundle-build",
            "minio-init",
            "prefect-deploy",
        ):
            self.services[name] = {"image": "teoria-test:latest", "profiles": ["jobs"]}
        self.services["minio-init"]["environment"] = {
            "SPECIFICATION_WORKER_PASSWORD": "synthetic",
            "SPECIFICATION_API_PASSWORD": "synthetic",
        }

    def call(self, command, **kwargs):
        self.calls.append(command)
        if "teoria.entrypoints.deployment_check" in command and self.fail_verify:
            raise subprocess.CalledProcessError(1, command)
        if "teoria.integrations.prefect.maintenance" in command:
            return json.dumps(
                {"active": 0}
                if command[-1] == "active"
                else {
                    "pools": [],
                    "schedules": [],
                    "deployment_ids": [],
                    "deployment_pools": {},
                }
            )
        if "config" in command:
            return json.dumps({"services": self.services})
        if command[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": "sha256:current"}])
        return ""

    def subprocess_run(self, command, **kwargs):
        self.calls.append(command)
        code = 0
        if "run" in command:
            name = command[-1]
            self.jobs.append(name)
            code = int(name == self.fail_job)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                command, code, json.dumps([{"Id": "sha256:current"}])
            )
        return subprocess.CompletedProcess(command, code)

    def execute(self, *args):
        with (
            patch.object(deployment, "ROOT", self.root),
            patch.object(deployment, "call", self.call),
            patch.object(deployment.subprocess, "run", self.subprocess_run),
            patch("sys.argv", ["deployment.py", *args]),
        ):
            deployment.main()

    def test_all_selects_every_module_without_starting_tools(self):
        self.execute("config", "--all")
        command = self.calls[0]
        for module in deployment.MODULES:
            self.assertIn(str(self.root / f"compose_{module}.yaml"), command)
        self.assertFalse(any("up" in command for command in self.calls))

    def test_jobs_are_removed_and_workers_start_after_registration(self):
        self.execute("deploy", "--modules", "formatid")
        self.assertEqual(self.jobs[-1], "prefect-deploy")
        jobs = [c for c in self.calls if "run" in c]
        self.assertTrue(
            all("--rm" in c and "--no-deps" in c and "never" in c for c in jobs)
        )
        registered = next(
            i
            for i, c in enumerate(self.calls)
            if "run" in c and c[-1] == "prefect-deploy"
        )
        started = next(
            i for i, c in enumerate(self.calls) if "up" in c and "prefect-worker" in c
        )
        self.assertGreater(started, registered)
        self.assertFalse(any("build" in c for c in self.calls))
        saved = json.loads((self.root / ".state/teoria/deployment.json").read_text())
        self.assertEqual(saved["modules"], ["formatid"])
        self.assertTrue(saved["prepared"])

    def test_mlflow_database_is_prepared_before_tracking_server_starts(self):
        for name in ("mlflow-postgres-init", "model-storage-init", "model-register"):
            self.services[name] = {"image": "teoria-test:latest", "profiles": ["jobs"]}
        self.services["mlflow-postgres-init"]["environment"] = {
            "TEORIA_MLFLOW_DB_PASSWORD": "synthetic"
        }
        self.services["mlflow"] = {"image": "teoria-test:latest"}
        self.services["demo-inference"] = {
            "image": "teoria-test:latest",
            "environment": {"TEORIA_DEMO_INFERENCE_TOKEN": "synthetic"},
        }
        self.execute("deploy", "--modules", "mlops")
        prepared = next(
            i
            for i, c in enumerate(self.calls)
            if "run" in c and c[-1] == "mlflow-postgres-init"
        )
        started = next(
            i for i, c in enumerate(self.calls) if "up" in c and "mlflow" in c
        )
        self.assertLess(prepared, started)
        self.assertFalse(any("mlflow-postgres" in c for c in self.calls))

    def test_failed_migration_does_not_start_application_or_mark_prepared(self):
        self.fail_job = "postgres-migrate"
        with self.assertRaisesRegex(RuntimeError, "postgres-migrate"):
            self.execute("deploy", "--modules", "formatid")
        self.assertNotIn("prefect-deploy", self.jobs)
        self.assertFalse(any("up" in c and "admin-api" in c for c in self.calls))
        self.assertFalse(
            json.loads((self.root / ".state/teoria/deployment.json").read_text())[
                "prepared"
            ]
        )

    def test_start_requires_successful_initial_deployment(self):
        with self.assertRaisesRegex(RuntimeError, "Run deploy once"):
            self.execute("start")
        self.assertFalse(any("up" in c for c in self.calls))

    def test_unchanged_deployment_keeps_distinct_rollback_images(self):
        folder = self.root / ".state/teoria"
        folder.mkdir(parents=True)
        (folder / "deployment.json").write_text(
            json.dumps(
                {
                    "modules": ["formatid"],
                    "prepared": True,
                    "images": ["sha256:current"],
                    "previous_images": ["sha256:rollback"],
                }
            )
        )
        self.execute("deploy")
        saved = json.loads((folder / "deployment.json").read_text())
        self.assertEqual(saved["previous_images"], ["sha256:rollback"])

    def test_start_does_not_build_migrate_or_register(self):
        self.execute("deploy", "--modules", "formatid")
        self.calls.clear()
        self.jobs.clear()
        self.execute("start")
        self.assertFalse(self.jobs)
        self.assertFalse(any("build" in command for command in self.calls))

    def test_failed_authenticated_verification_keeps_workers_stopped(self):
        self.fail_verify = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute("deploy", "--modules", "formatid")
        self.assertFalse(any("up" in c and "prefect-worker" in c for c in self.calls))
        self.assertFalse(
            json.loads((self.root / ".state/teoria/deployment.json").read_text())[
                "prepared"
            ]
        )

    def test_cleanup_preserves_current_rollback_and_container_references(self):
        folder = self.root / ".state/teoria"
        folder.mkdir(parents=True)
        (folder / "deployment.json").write_text(
            json.dumps(
                {
                    "modules": [],
                    "prepared": True,
                    "images": ["sha256:current"],
                    "previous_images": ["sha256:rollback"],
                }
            )
        )
        original = self.call

        def inventory(command, **kwargs):
            if command[:3] == ["docker", "image", "ls"]:
                self.assertIn("--all", command)
                return "current rollback busy old"
            if command == ["docker", "ps", "-aq"]:
                return "container"
            if command[:2] == ["docker", "inspect"]:
                return json.dumps([{"Image": "sha256:busy"}])
            if command[:3] == ["docker", "image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": "sha256:" + command[-1],
                            "RepoTags": ["teoria-test:" + command[-1]],
                        }
                    ]
                )
            return original(command, **kwargs)

        self.call = inventory
        self.execute("cleanup", "--apply")
        removals = [c for c in self.calls if c[:3] == ["docker", "image", "rm"]]
        self.assertEqual(removals, [["docker", "image", "rm", "teoria-test:old"]])
        self.assertFalse(any("prune" in c or "volume" in c for c in self.calls))

    def test_stop_shuts_application_services_down_before_infrastructure(self):
        self.execute("deploy", "--modules", "formatid")
        self.calls.clear()
        original = self.call

        def running(command, **kwargs):
            if "ps" in command and "--status" in command:
                self.calls.append(command)
                return "admin-api prefect-server prefect-worker"
            return original(command, **kwargs)

        self.call = running
        self.execute("stop")
        stops = [c for c in self.calls if "stop" in c]
        application_stop = next(i for i, c in enumerate(stops) if "prefect-server" in c)
        self.assertLess(application_stop, len(stops) - 1)
        self.assertIn("*", stops[-1])
        self.assertTrue(any("prefect-worker" in c for c in stops[:application_stop]))

    def test_build_uses_one_target_per_image_and_pins_the_builder(self):
        for name in ("admin-api", "nginx"):
            self.services[name]["build"] = {"context": "."}
        self.services["mcp"] = {
            "image": "teoria-mcp:latest",
            "build": {"context": "."},
            "profiles": ["jobs"],
        }
        self.execute("build", "--modules", "semantic")
        build = next(c for c in self.calls if "build" in c)
        self.assertIn("admin-api", build)
        self.assertNotIn("nginx", build)
        self.assertIn("mcp", build)
        created = next(c for c in self.calls if c[:3] == ["docker", "buildx", "create"])
        self.assertIn("image=moby/buildkit:v0.30.0", created)

    def test_cleanup_preserves_other_modules_even_when_image_roles_overlap(self):
        self.services["admin-api"]["build"] = {"labels": {"io.teoria.role": "admin"}}
        folder = self.root / ".state/teoria"
        folder.mkdir(parents=True)
        (folder / "deployment.json").write_text(
            json.dumps({"modules": [], "prepared": True})
        )
        original = self.call

        def inventory(command, **kwargs):
            if command[:3] == ["docker", "image", "ls"]:
                return "staged dangling"
            if command[:3] == ["docker", "image", "inspect"]:
                identifier = command[-1]
                return json.dumps(
                    [
                        {
                            "Id": "sha256:" + identifier,
                            "RepoTags": ["teoria-model-worker:latest"]
                            if identifier == "staged"
                            else [],
                            "Config": {"Labels": {"io.teoria.role": "admin"}},
                        }
                    ]
                )
            return original(command, **kwargs)

        self.call = inventory
        self.execute("cleanup", "--apply")
        removals = [c for c in self.calls if c[:3] == ["docker", "image", "rm"]]
        self.assertEqual(removals, [["docker", "image", "rm", "sha256:dangling"]])

    def test_diagnosis_worker_is_selected_only_when_enabled(self):
        self.services["metadata-assessment-worker"] = {
            "image": "teoria-test:latest",
            "profiles": ["assessment"],
        }
        self.services["admin-api"]["environment"] = {
            "TEORIA_ASSESSMENT_ENABLED": "true"
        }
        with patch("builtins.print") as output:
            self.execute("config", "--modules", "semantic")
        rendered = json.loads(output.call_args.args[0])
        self.assertIn("metadata-assessment-worker", rendered["services"])
        self.assertNotIn("metadata-assessment-worker", rendered["jobs"])
        self.services["admin-api"]["environment"]["TEORIA_ASSESSMENT_ENABLED"] = "false"
        with patch("builtins.print") as output:
            self.execute("config", "--modules", "semantic")
        self.assertNotIn(
            "metadata-assessment-worker",
            json.loads(output.call_args.args[0])["services"],
        )

    def test_start_rejects_changed_configuration_without_recreating_services(self):
        self.execute("deploy", "--modules", "formatid")
        self.calls.clear()
        self.services["admin-api"]["image"] = "teoria-test:new-release"
        with self.assertRaisesRegex(RuntimeError, "Configuration changed"):
            self.execute("start")
        self.assertFalse(any("up" in command for command in self.calls))
