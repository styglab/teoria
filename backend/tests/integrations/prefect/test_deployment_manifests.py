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


@pytest.mark.parametrize("kind", ["ingestion", "legal-information", "metadata", "model-operations"])
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
        "process" if kind in {"metadata", "model-operations"} else "kubernetes"
    )


@pytest.mark.parametrize("backend", ["process", "kubernetes"])
def test_only_generic_model_workflows_are_registered_even_with_legacy_demo_flag(monkeypatch, backend):
    monkeypatch.setenv("TEORIA_MODEL_DEMO_ENABLED", "true")
    document = load_deployment_manifest(ROOT / "backend", "model-operations", backend)
    assert {d["name"] for d in document["deployments"]} == {"model-train", "model-deploy", "model-stop"}


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
