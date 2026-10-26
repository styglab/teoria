"""Protect persistent data isolation and the supported Compose auth contract."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

COMPOSE_ROOT = Path(__file__).resolve().parents[3] / "deploy/compose"


class ComposeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env_file = Path(self.directory.name) / ".env"
        self.env_file.write_text((COMPOSE_ROOT / ".env.example").read_text())
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("TEORIA_", "OPENMETADATA_", "COMPOSE_"))
        }
        for key in (
            "TEORIA_ADMIN_API_TOKEN",
            "TEORIA_RUNTIME_API_TOKEN",
            "TEORIA_OPA_CONTROL_PLANE_TOKEN",
            "TEORIA_PREFECT_USERNAME",
            "TEORIA_PREFECT_PASSWORD",
            "TEORIA_LOCAL_RUNTIME_DB_PASSWORD",
        ):
            self.environment[key] = "synthetic-validation-value"

    def config(self, project):
        return subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(self.env_file),
                "-f",
                str(COMPOSE_ROOT / "compose.yaml"),
                "-p",
                project,
                "--profile",
                "*",
                "config",
                "--format",
                "json",
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def resolved(self, project):
        result = self.config(project)
        self.assertEqual(result.returncode, 0, "Compose configuration must resolve")
        return json.loads(result.stdout)

    def test_gateway_serves_ui_without_a_separate_ui_service(self):
        services = self.resolved("teoria-test-gateway")["services"]
        self.assertNotIn("admin-ui", services)
        gateway = services["nginx"]
        self.assertEqual(gateway["build"]["target"], "gateway")
        self.assertTrue(gateway["build"]["dockerfile"].endswith("frontend/Dockerfile"))
        self.assertNotIn("admin-ui", gateway["depends_on"])

    def test_every_service_has_explicit_cpu_and_memory_limits(self):
        services = self.resolved("teoria-test-budgets")["services"]
        for name, service in services.items():
            with self.subTest(service=name):
                self.assertGreater(float(service.get("cpus", 0)), 0)
                self.assertGreater(int(service.get("mem_limit", 0)), 0)

    def test_redis_data_budgets_leave_headroom_for_persistence(self):
        services = self.resolved("teoria-test-redis-budgets")["services"]
        for name in ("runtime-redis", "prefect-redis"):
            service = services[name]
            command = service["command"]
            data_limit = (
                int(command[command.index("--maxmemory") + 1].removesuffix("mb"))
                * 1024**2
            )
            self.assertGreaterEqual(int(service["mem_limit"]), data_limit * 2)
        command = services["prefect-redis"]["command"]
        self.assertEqual(command[command.index("--maxmemory-policy") + 1], "noeviction")

    def test_default_project_preserves_existing_persistent_volume_names(self):
        config = self.resolved("teoria")
        for key, suffix in {
            "postgres": "data-db",
            "platform-postgres": "platform-db",
            "runtime-artifacts": "runtime-artifacts",
            "opa-bundles": "opa-bundles",
            "opa-signing-keys": "opa-signing-keys",
            "opa-state": "opa-state",
        }.items():
            self.assertEqual(config["volumes"][key]["name"], "teoria_" + suffix)

    def test_different_projects_share_no_managed_volumes(self):
        first = self.resolved("teoria-test-dev")
        second = self.resolved("teoria-test-staging")
        names = lambda config: {item["name"] for item in config["volumes"].values()}
        self.assertTrue(names(first).isdisjoint(names(second)))

    def test_compose_requires_admin_credentials_and_keeps_bearer_auth(self):
        self.environment["TEORIA_ADMIN_AUTH_MODE"] = "disabled"
        config = self.resolved("teoria-test-auth")
        self.assertEqual(
            config["services"]["admin-api"]["environment"]["TEORIA_ADMIN_AUTH_MODE"],
            "bearer",
        )
        self.environment["TEORIA_ADMIN_API_TOKEN"] = ""
        missing = self.config("teoria-test-auth")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("TEORIA_ADMIN_API_TOKEN", missing.stderr)

    def test_example_uses_container_dns_for_openmetadata(self):
        config = self.resolved("teoria-test-metadata")
        environment = config["services"]["admin-api"]["environment"]
        self.assertEqual(
            environment["TEORIA_OPENMETADATA_BASE_URL"],
            "http://openmetadata-server:8585/api",
        )
        self.assertEqual(environment["TEORIA_OPENMETADATA_ENABLED"], "true")

    def test_pipeline_worker_has_resource_and_execution_limits(self):
        services = self.resolved("teoria-test-limits")["services"]
        worker = services["prefect-worker"]
        self.assertEqual(worker["cpus"], 4)
        self.assertEqual(int(worker["mem_limit"]), 8 * 1024**3)
        self.assertEqual(worker["environment"]["TEORIA_PIPELINE_CONCURRENCY"], "2")
        registration = services["prefect-deploy"]
        self.assertEqual(
            registration["command"],
            [
                "teoria-pipelines",
                "register",
                "--backend",
                "process",
                "--kind",
                "ingestion",
            ],
        )
        self.assertNotIn(
            "TEORIA_PIPELINE_BACKFILL_CONCURRENCY", registration["environment"]
        )
        self.assertEqual(
            worker["command"],
            ["teoria-pipelines", "worker", "--pool", "teoria-specification"],
        )
        self.assertFalse(
            any(name.startswith("TEORIA_CONNECTOR_") for name in worker["environment"])
        )
        self.assertEqual(
            worker["environment"]["TEORIA_SPECIFICATION_PARSER_PYTHON"],
            "/opt/kory_parser/bin/python",
        )

    def test_runtime_can_read_specification_evidence_without_worker_write_or_model_access(self):
        services = self.resolved("teoria-test-evidence")["services"]
        runtime = services["runtime-api"]
        worker = services["prefect-worker"]
        target = "/app/specification_artifacts"
        runtime_mount = next(v for v in runtime["volumes"] if v["target"] == target)
        worker_mount = next(v for v in worker["volumes"] if v["target"] == target)
        self.assertEqual(runtime_mount["source"], worker_mount["source"])
        self.assertTrue(runtime_mount["read_only"])
        self.assertFalse(worker_mount.get("read_only", False))
        self.assertFalse(any(v["target"] == "/home/teoria/.codex" for v in runtime["volumes"]))

    def test_law_credentials_are_isolated_from_document_worker(self):
        services = self.resolved("teoria-test-law")["services"]
        law = services["prefect-law-worker"]
        self.assertEqual(
            law["command"],
            ["teoria-pipelines", "worker", "--pool", "teoria-legal-information"],
        )
        self.assertEqual(law["environment"]["TEORIA_PIPELINE_CONCURRENCY"], "1")
        self.assertIn("TEORIA_CONNECTOR_MOLEG_LAW_API_KEY", law["environment"])
        self.assertNotIn(
            "TEORIA_CONNECTOR_MOLEG_LAW_API_KEY",
            services["prefect-worker"]["environment"],
        )


if __name__ == "__main__":
    unittest.main()
