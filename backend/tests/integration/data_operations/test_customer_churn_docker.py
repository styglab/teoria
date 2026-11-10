"""Opt-in Docker execution of seed → training → model release → authenticated prediction.

Build model-training, model-serving and model-dispatcher Dockerfile targets with
teoria-<target>:validation tags, then run with TEORIA_TEST_MLOPS_DOCKER=1.
All databases, credentials, networks and release volumes are isolated and synthetic.
MLflow uses a local artifact directory; this does not validate production S3 or K3s.
"""

import os
import time
import uuid
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("TEORIA_TEST_MLOPS_DOCKER") != "1",
    reason="explicit Docker MLOps smoke test",
)


def test_customer_churn_docker_training_and_serving():
    docker = pytest.importorskip("docker")
    client = docker.from_env()
    project = "teoria-mlops-check-" + uuid.uuid4().hex[:8]
    network = client.networks.create(project + "_default")
    volume = client.volumes.create(project + "_release")
    containers = []
    auth = "synthetic:smoke-test"
    token = "synthetic-inference-token-for-smoke-test"
    base = {
        "PREFECT_API_URL": "http://prefect-server:4200/api",
        "PREFECT_API_AUTH_STRING": auth,
    }

    def start(role, image, command, env=None, **kw):
        c = client.containers.run(
            image,
            command,
            name=project + "-" + role,
            detach=True,
            network=network.name,
            environment=env or {},
            mem_limit="2g",
            nano_cpus=2000000000,
            **kw,
        )
        containers.append(c)
        network.disconnect(c)
        network.connect(c, aliases=[role])
        return c

    def execute(c, cmd):
        result = c.exec_run(cmd)
        if result.exit_code:
            raise RuntimeError(c.name + ": " + result.output.decode()[-10000:])
        return result.output.decode()

    def wait(c, cmd):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if c.exec_run(cmd).exit_code == 0:
                return
            time.sleep(1)
        raise RuntimeError(
            "readiness failed: " + c.name + " " + c.logs(tail=20).decode()
        )

    try:
        postgres = start(
            "postgres",
            "postgres:17",
            ["postgres"],
            {"POSTGRES_PASSWORD": "synthetic", "POSTGRES_DB": "teoria_data"},
        )
        wait(postgres, ["pg_isready", "-U", "postgres", "-d", "teoria_data"])
        sql = (
            "CREATE ROLE teoria_metadata;\n"
            + (
                Path(__file__).resolve().parents[3]
                / "migrations/data/096_mlops_demo_customers.sql"
            ).read_text()
        )
        result = postgres.exec_run(
            [
                "sh",
                "-c",
                "printf '%s' \"$SMOKE_SQL\" | psql -v ON_ERROR_STOP=1 -U postgres -d teoria_data",
            ],
            environment={"SMOKE_SQL": sql},
        )
        assert result.exit_code == 0, result.output.decode()
        server = start(
            "prefect-server",
            "teoria-model-training:validation",
            ["prefect", "server", "start", "--host", "0.0.0.0"],
            {
                "PREFECT_SERVER_API_AUTH_STRING": auth,
                "PREFECT_SERVER_ANALYTICS_ENABLED": "false",
            },
        )
        probe = [
            "python",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://localhost:4200/api/health')",
        ]
        wait(server, probe)
        mlflow = start(
            "mlflow",
            "teoria-model-training:validation",
            [
                "mlflow",
                "server",
                "--host",
                "0.0.0.0",
                "--port",
                "5000",
                "--workers",
                "1",
                "--static-prefix",
                "/mlflow",
                "--backend-store-uri",
                "sqlite:////tmp/mlflow.db",
                "--serve-artifacts",
                "--artifacts-destination",
                "/tmp/models",
            ],
            {
                "MLFLOW_SERVER_ALLOWED_HOSTS": "mlflow:5000,localhost:5000,127.0.0.1:5000"
            },
        )
        wait(
            mlflow,
            [
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://localhost:5000/mlflow/health')",
            ],
        )
        env = {
            **base,
            "MLFLOW_TRACKING_URI": "http://mlflow:5000/mlflow",
            "TEORIA_PIPELINE_DATA_DATABASE_URL": "postgresql://postgres:synthetic@postgres:5432/teoria_data",
            "TEORIA_MODEL_TRAINING_IMAGE": "teoria-model-training:validation",
            "TEORIA_MODEL_DOCKER_NETWORK": network.name,
        }
        control = start(
            "control",
            "teoria-model-dispatcher:validation",
            ["sleep", "600"],
            env,
            user="root",
        )
        execute(
            control,
            [
                "teoria-pipelines",
                "register",
                "--backend",
                "process",
                "--kind",
                "model-operations",
                "--pipelines",
                "/app/backend",
            ],
        )
        print("Deployment registration passed", flush=True)
        inference = start(
            "demo-inference",
            "teoria-model-serving:validation",
            ["teoria-demo-inference"],
            {
                "MLFLOW_TRACKING_URI": "http://mlflow:5000/mlflow",
                "TEORIA_DEMO_RELEASE_DIRECTORY": "/app/model_release",
                "TEORIA_DEMO_INFERENCE_TOKEN": token,
            },
            volumes={volume.name: {"bind": "/app/model_release", "mode": "ro"}},
            labels={
                "io.teoria.role": "demo-inference",
                "com.docker.compose.project": project,
                "com.docker.compose.service": "demo-inference",
            },
        )
        wait(
            inference,
            [
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://localhost:8003/live')",
            ],
        )
        start(
            "dispatcher",
            "teoria-model-dispatcher:validation",
            [
                "prefect",
                "worker",
                "start",
                "--pool",
                "teoria-model-training-docker",
                "--type",
                "docker",
                "--limit",
                "1",
            ],
            env,
            user="root",
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}
            },
        )
        start(
            "deployer",
            "teoria-model-training:validation",
            [
                "prefect",
                "worker",
                "start",
                "--pool",
                "teoria-model-deployment",
                "--limit",
                "1",
            ],
            {
                **base,
                "MLFLOW_TRACKING_URI": "http://mlflow:5000/mlflow",
                "TEORIA_DEMO_RELEASE_DIRECTORY": "/app/model_release",
                "TEORIA_DEMO_INFERENCE_TOKEN": token,
                "TEORIA_COMPOSE_PROJECT_NAME": project,
            },
            user="root",
            volumes={
                volume.name: {"bind": "/app/model_release", "mode": "rw"},
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            },
        )
        code = """
    from prefect.deployments import run_deployment
    for name, parameters in [
        ("합성 고객 데이터 준비/demo-seed-customers", {}),
        ("합성 고객 모델 학습·배포/demo-customer-churn-pipeline", {"deploy": True})
    ]:
        run=run_deployment(name, parameters=parameters, timeout=180, poll_interval=1)
        assert run.state.is_completed(), (name, str(run.state))
        print(name+": COMPLETED", flush=True)
    """
        print(execute(control, ["python", "-c", dedent(code)]), flush=True)
        code = """
    import httpx
    r=httpx.get('http://demo-inference:8003/health');r.raise_for_status();assert r.json()['model_version']==1
    print('Serving fixed model version 1: healthy')
    """
        print(execute(control, ["python", "-c", dedent(code)]), flush=True)
        deadline = time.monotonic() + 20
        while True:
            jobs = client.containers.list(all=True, filters={"network": network.name})
            if {c.id for c in jobs} <= {c.id for c in containers}:
                break
            assert time.monotonic() < deadline, (
                "training containers remained after execution"
            )
            time.sleep(1)
        print(
            "One-off training containers removed; authenticated prediction verified by deployment Flow",
            flush=True,
        )
    except BaseException:
        for c in containers:
            if c.name.endswith(("dispatcher", "deployer")):
                print(c.name, c.logs(tail=30).decode(), flush=True)
        raise
    finally:
        for c in client.containers.list(all=True, filters={"network": network.name}):
            c.remove(force=True)
        network.remove()
        volume.remove()
        client.close()
