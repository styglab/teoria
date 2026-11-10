"""Keep shared workflow semantics independent from execution environments."""

from pathlib import Path
import shutil

import pytest
import yaml

from teoria.integrations.prefect.deployment_manifests import (
    deployment_path,
    load_deployment_manifest,
    load_execution_policy,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("kind", ["ingestion", "legal-information", "metadata"])
def test_environments_share_flow_parameters_and_schedules(kind):
    compose = load_deployment_manifest(ROOT / "backend", kind, "process")
    kubernetes = load_deployment_manifest(ROOT / "backend", kind, "kubernetes")
    for left, right in zip(
        compose["deployments"], kubernetes["deployments"], strict=True
    ):
        left.pop("work_pool")
        right.pop("work_pool")
        if kind == "metadata":
            left["parameters"].pop("image")
            left["parameters"].pop("network")
            right["parameters"].pop("image")
        assert left == right
    compose_policy = load_execution_policy(ROOT / "backend", kind, "process")
    kubernetes_policy = load_execution_policy(ROOT / "backend", kind, "kubernetes")
    assert compose_policy["pools"][0]["type"] == "process"
    assert kubernetes_policy["pools"][0]["type"] == (
        "process" if kind == "metadata" else "kubernetes"
    )


def test_kubernetes_does_not_register_compose_only_demo():
    with pytest.raises(ValueError, match="not supported"):
        load_deployment_manifest(ROOT / "backend", "model-operations", "kubernetes")


@pytest.mark.parametrize("patch", ["schedules", "parameters", "queue"])
def test_environment_binding_cannot_drift_shared_contract_or_use_unknown_queue(
    tmp_path, patch
):
    shutil.copytree(
        ROOT / "backend/config/specification_processing",
        tmp_path / "backend/config/specification_processing",
    )
    target = deployment_path(tmp_path / "backend", "ingestion")
    target.parent.mkdir(parents=True)
    shutil.copy2(deployment_path(ROOT / "backend", "ingestion"), target)
    policy = yaml.safe_load(target.read_text())
    if patch == "schedules":
        policy["deployments"][0]["schedules"] = []
    elif patch == "parameters":
        policy["deployments"][0]["parameters"] = {"target_specifications": 999}
    else:
        policy["deployments"][0]["work_pool"]["work_queue_name"] = "unknown"
    target.write_text(yaml.safe_dump(policy))
    with pytest.raises(ValueError):
        load_deployment_manifest(tmp_path / "backend", "ingestion")


async def test_docker_training_pool_updates_without_changing_deployment_pool(
    monkeypatch,
):
    pytest.importorskip("prefect_docker")
    from unittest.mock import AsyncMock
    from teoria.integrations.prefect.deployment import configure_pool

    client = AsyncMock()
    from types import SimpleNamespace

    monkeypatch.setenv("TEORIA_MODEL_TRAINING_IMAGE", "training:test")
    monkeypatch.setenv("TEORIA_MODEL_DOCKER_NETWORK", "isolated_default")
    client.read_work_pool.side_effect = [
        SimpleNamespace(type="docker"),
        SimpleNamespace(type="process"),
    ]
    await configure_pool(
        client,
        backend="process",
        kind="model-operations",
        pipeline_root=ROOT / "backend",
    )
    client.create_work_pool.assert_not_awaited()
    client.update_work_pool.assert_awaited_once()
    assert client.update_work_pool.await_args.args[0] == "teoria-model-training-docker"


async def test_training_template_resolves_credentials_only_on_worker(monkeypatch):
    pytest.importorskip("prefect_docker")
    from unittest.mock import AsyncMock
    from prefect_docker.worker import DockerWorkerJobConfiguration
    from teoria.integrations.prefect.deployment import docker_job_template

    monkeypatch.setenv("TEORIA_MODEL_TRAINING_IMAGE", "training:test")
    monkeypatch.setenv("TEORIA_MODEL_DOCKER_NETWORK", "isolated_default")
    policy = load_execution_policy(ROOT / "backend", "model-operations", "process")
    template = docker_job_template(policy["pools"][0])
    from prefect.server.schemas.actions import WorkPoolCreate

    WorkPoolCreate(name="training-test", type="docker", base_job_template=template)
    monkeypatch.setenv(
        "TEORIA_PIPELINE_DATA_DATABASE_URL", "postgresql://synthetic-secret"
    )
    monkeypatch.setenv("PREFECT_API_AUTH_STRING", "synthetic:worker-secret")
    monkeypatch.setenv("PREFECT_API_URL", "http://prefect-server:4200/api")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000/mlflow")
    assert "synthetic-secret" not in str(template)
    assert "worker-secret" not in str(template)
    config = await DockerWorkerJobConfiguration.from_template_and_values(
        template, {}, client=AsyncMock()
    )
    assert config.image == "training:test"
    assert config.networks == ["isolated_default"]
    assert (
        config.env["TEORIA_PIPELINE_DATA_DATABASE_URL"]
        == "postgresql://synthetic-secret"
    )
    assert config.env["PREFECT_API_AUTH_STRING"] == "synthetic:worker-secret"
    assert config.auto_remove and config.volumes == [] and not config.privileged
    assert config.mem_limit == "2g"
    assert config.container_create_kwargs["nano_cpus"] == 2000000000
