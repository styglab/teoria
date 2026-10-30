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


async def test_existing_demo_pool_configuration_is_preserved():
    from unittest.mock import AsyncMock
    from teoria.integrations.prefect.deployment import configure_pool

    client = AsyncMock()
    client.read_work_pool.return_value.type = "process"
    await configure_pool(
        client,
        backend="process",
        kind="model-operations",
        pipeline_root=ROOT / "backend",
    )
    client.create_work_pool.assert_not_awaited()
    client.update_work_pool.assert_not_awaited()
