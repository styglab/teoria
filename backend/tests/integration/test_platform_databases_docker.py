"""Opt-in isolated PostgreSQL verification of unified platform database provisioning."""
import os
from pathlib import Path
import subprocess
import time
import uuid

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.getenv("TEORIA_TEST_FEATURE_DATABASES_DOCKER") != "1",
    reason="explicit isolated PostgreSQL container test",
)
ROOT = Path(__file__).resolve().parents[3]


def test_selected_databases_roles_and_repeatable_provisioning():
    name = "teoria-feature-db-check-" + uuid.uuid4().hex[:10]

    def run(*args, **kwargs):
        return subprocess.run(args, text=True, capture_output=True, check=True, timeout=60, **kwargs).stdout

    try:
        run("docker", "run", "--detach", "--name", name, "--network", "none",
            "--env", "POSTGRES_USER=platform_admin", "--env", "POSTGRES_PASSWORD=synthetic-only",
            "postgres:17")
        for _ in range(60):
            result = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "platform_admin"], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Isolated PostgreSQL did not become ready")
        document = yaml.safe_load((ROOT / "deploy/kubernetes/base/services/postgres/initialize_platform.yaml").read_text())
        command = document["spec"]["template"]["spec"]["containers"][0]["command"]
        args = ["docker", "exec", "--env", "PGHOST=127.0.0.1", "--env", "PGUSER=platform_admin",
                "--env", "PGDATABASE=postgres", "--env", "PGPASSWORD=synthetic-only"]
        for key in ("TEORIA_LOCAL_APP_DB_PASSWORD", "TEORIA_LOCAL_PREFECT_DB_PASSWORD", "TEORIA_MLFLOW_DB_PASSWORD", "OPENMETADATA_DB_PASSWORD"):
            args += ["--env", key + "=synthetic-only"]
        run(*args, name, *command)
        run(*args, name, *command)
        rows = run("docker", "exec", name, "psql", "-U", "platform_admin", "-d", "postgres", "-Atc",
            "SELECT datname || ':' || pg_get_userbyid(datdba) FROM pg_database WHERE datname NOT IN ('postgres','platform_admin','template0','template1')")
        assert set(rows.splitlines()) == {"teoria_app:teoria_app", "prefect:prefect", "openmetadata_db:openmetadata_user", "mlflow:mlflow"}
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=30)
