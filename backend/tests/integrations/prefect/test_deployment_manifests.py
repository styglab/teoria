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
def test_kubernetes_preserves_shared_flow_parameters_and_schedules(kind):
    path = ROOT / "backend/config" / {"ingestion":"specification_processing", "legal-information":"legal_information", "metadata":"metadata_management", "model-operations":"model_operations"}[kind] / "prefect_deployments.yaml"
    shared = yaml.safe_load(path.read_text())
    rendered = load_deployment_manifest(ROOT / "backend", kind)
    for left, right in zip(shared["deployments"], rendered["deployments"], strict=True):
        assert right["schedules"] == left["schedules"]
        assert right["entrypoint"] == left["entrypoint"]
        for key, value in left.get("parameters", {}).items():
            assert right["parameters"][key] == value
    policy = load_execution_policy(ROOT / "backend", kind, "kubernetes")
    assert policy["pools"][0]["type"] == ("process" if kind in {"metadata", "model-operations"} else "kubernetes")


def test_only_generic_model_workflows_are_registered_even_with_legacy_demo_flag(monkeypatch):
    monkeypatch.setenv("TEORIA_MODEL_DEMO_ENABLED", "true")
    document = load_deployment_manifest(ROOT / "backend", "model-operations")
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


@pytest.mark.parametrize("enabled", [None, "true", "false"])
def test_registration_respects_explicit_schedule_policy_without_changing_shared_defaults(monkeypatch, enabled):
    from teoria.integrations.prefect import deployment
    captured = []
    if enabled is None:
        monkeypatch.delenv("TEORIA_PREFECT_SCHEDULES_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TEORIA_PREFECT_SCHEDULES_ENABLED", enabled)

    def configured(coroutine):
        coroutine.close()
        return {"metadata": "teoria-metadata"}

    def deploy(command, **kwargs):
        captured.append(yaml.safe_load(Path(command[-1]).read_text()))

    monkeypatch.setattr(deployment.asyncio, "run", configured)
    monkeypatch.setattr(deployment.subprocess, "run", deploy)
    deployment.register_deployments(ROOT / "backend", backend="kubernetes", kind="metadata")
    assert captured[0]["deployments"][0]["schedules"][0]["active"] == (enabled != "false")
    assert load_deployment_manifest(ROOT / "backend", "metadata", "kubernetes")["deployments"][0]["schedules"][0]["active"] is True
