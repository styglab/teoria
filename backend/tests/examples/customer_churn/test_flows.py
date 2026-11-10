from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from teoria.examples.customer_churn import flows


@pytest.mark.asyncio
@pytest.mark.parametrize("deploy", [False, True])
async def test_parent_uses_registered_version_and_explicit_deployment(
    monkeypatch, deploy
):
    trained = {
        "model_name": "demo",
        "model_version": "7",
        "run_id": "ml-run",
        "dataset_checksum": "sha",
    }
    monkeypatch.setattr(
        flows, "train_demo_customer_churn", AsyncMock(return_value=trained)
    )
    remote = AsyncMock(return_value=SimpleNamespace(id="deploy-run"))
    monkeypatch.setattr(flows, "run_child_deployment", remote)
    artifact = AsyncMock()
    monkeypatch.setattr(flows, "create_markdown_artifact", artifact)
    result = await flows.customer_churn_pipeline.fn(
        requested_by="admin:real", deploy=deploy
    )
    assert result["model_version"] == "7"
    if deploy:
        assert remote.await_args.kwargs["parameters"] == {
            "model_version": 7,
            "requested_by": "admin:real",
        }
        assert result["deployment_run_id"] == "deploy-run"
    else:
        remote.assert_not_awaited()
        assert result["deployment_status"] == "not_requested"
    artifact.assert_awaited_once()


@pytest.mark.asyncio
async def test_training_failure_prevents_deployment(monkeypatch):
    monkeypatch.setattr(
        flows,
        "train_demo_customer_churn",
        AsyncMock(side_effect=ValueError("quality gate")),
    )
    remote = AsyncMock()
    monkeypatch.setattr(flows, "run_child_deployment", remote)
    with pytest.raises(ValueError, match="quality gate"):
        await flows.customer_churn_pipeline.fn(deploy=True)
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_remote_deployment_does_not_publish_success(monkeypatch):
    monkeypatch.setattr(
        flows,
        "train_demo_customer_churn",
        AsyncMock(return_value={"model_version": "7"}),
    )
    monkeypatch.setattr(
        flows, "run_child_deployment", AsyncMock(side_effect=RuntimeError("failed"))
    )
    artifact = AsyncMock()
    monkeypatch.setattr(flows, "create_markdown_artifact", artifact)
    with pytest.raises(RuntimeError, match="failed"):
        await flows.customer_churn_pipeline.fn(deploy=True)
    artifact.assert_not_awaited()


@pytest.mark.asyncio
async def test_quality_gate_prevents_registration(monkeypatch):
    monkeypatch.setattr(
        flows, "read_training_task", AsyncMock(return_value=([], [], "sha"))
    )
    monkeypatch.setattr(
        flows, "prepare_task", AsyncMock(return_value=("frame", "split"))
    )
    monkeypatch.setattr(flows, "fit_task", AsyncMock(return_value="model"))
    monkeypatch.setattr(
        flows, "evaluate_task", AsyncMock(side_effect=ValueError("quality gate"))
    )
    register = AsyncMock()
    monkeypatch.setattr(flows, "register_task", register)
    with pytest.raises(ValueError, match="quality gate"):
        await flows.train_demo_customer_churn.fn()
    register.assert_not_awaited()


@pytest.mark.asyncio
async def test_example_owns_model_identity_and_training_provenance(monkeypatch):
    from teoria.examples.customer_churn import MODEL_NAME

    monkeypatch.setenv("TEORIA_MODEL_TRAINING_IMAGE", "training@sha256:fixed")
    calls = []

    def register(*args, **kwargs):
        calls.append(kwargs)
        return {"model_name": kwargs["model_name"], "model_version": "7"}

    monkeypatch.setattr(flows, "register_model", register)
    monkeypatch.setattr(
        flows, "flow_run", SimpleNamespace(id="child", parent_flow_run_id="parent")
    )
    result = await flows.register_task.fn(
        "model", {"roc_auc": 0.8}, "frame", "dataset-sha", "authenticated-admin"
    )
    assert result["synthetic"] is True and result["dataset_checksum"] == "dataset-sha"
    assert calls[0]["model_name"] == MODEL_NAME
    assert calls[0]["parameters"]["personal_attributes_in_features"] is False
    assert calls[0]["tags"] == {
        "teoria.synthetic": "true",
        "teoria.training_image": "training@sha256:fixed",
        "teoria.requested_by": "authenticated-admin",
        "teoria.prefect_flow_run_id": "child",
        "teoria.prefect_pipeline_run_id": "parent",
    }
