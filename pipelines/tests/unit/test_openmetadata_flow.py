from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from teoria_pipelines.metadata.openmetadata import (
    _required_environment,
    run_openmetadata_ingestion_container,
)


def test_required_environment_rejects_missing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENMETADATA_INGESTION_BOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="OPENMETADATA_INGESTION_BOT_TOKEN"):
        _required_environment("OPENMETADATA_INGESTION_BOT_TOKEN")


def test_ingestion_task_runs_and_removes_ephemeral_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEORIA_METADATA_DB_PASSWORD", "database-secret")
    monkeypatch.setenv("OPENMETADATA_INGESTION_BOT_TOKEN", "jwt-secret")
    monkeypatch.setenv(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE",
        "teoria-openmetadata-ingestion:2.0.5",
    )
    container = MagicMock()
    container.logs.return_value = [b"metadata synchronized\n"]
    container.wait.return_value = {"StatusCode": 0}
    client = MagicMock()
    client.containers.run.return_value = container
    docker_module = SimpleNamespace(from_env=MagicMock(return_value=client))

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.metadata.openmetadata.get_run_logger") as logger,
    ):
        result = run_openmetadata_ingestion_container.fn(
            image="teoria-openmetadata-ingestion:2.0.5",
            network="teoria_default",
            timeout_seconds=30,
        )

    assert result == {
        "status": "completed",
        "status_code": 0,
        "image": "teoria-openmetadata-ingestion:2.0.5",
    }
    client.containers.run.assert_called_once()
    call = client.containers.run.call_args
    assert call.kwargs["auto_remove"] is False
    assert call.kwargs["environment"] == {
        "TEORIA_METADATA_DB_PASSWORD": "database-secret",
        "OPENMETADATA_INGESTION_BOT_TOKEN": "jwt-secret",
    }
    logger.return_value.info.assert_called_once_with("metadata synchronized")
    container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once_with()


def test_ingestion_task_fails_on_nonzero_exit_and_removes_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEORIA_METADATA_DB_PASSWORD", "database-secret")
    monkeypatch.setenv("OPENMETADATA_INGESTION_BOT_TOKEN", "jwt-secret")
    monkeypatch.setenv(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE",
        "teoria-openmetadata-ingestion:2.0.5",
    )
    container = MagicMock()
    container.logs.return_value = []
    container.wait.return_value = {"StatusCode": 7}
    client = MagicMock()
    client.containers.run.return_value = container
    docker_module = SimpleNamespace(from_env=MagicMock(return_value=client))

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.metadata.openmetadata.get_run_logger"),
        pytest.raises(RuntimeError, match="status 7"),
    ):
        run_openmetadata_ingestion_container.fn(
            image="teoria-openmetadata-ingestion:2.0.5",
            network="teoria_default",
            timeout_seconds=30,
        )

    container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once_with()


def test_ingestion_task_rejects_non_allowlisted_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEORIA_METADATA_DB_PASSWORD", "database-secret")
    monkeypatch.setenv("OPENMETADATA_INGESTION_BOT_TOKEN", "jwt-secret")
    monkeypatch.setenv(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE",
        "teoria-openmetadata-ingestion:2.0.5",
    )
    docker_module = SimpleNamespace(from_env=MagicMock())

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.metadata.openmetadata.get_run_logger"),
        pytest.raises(RuntimeError, match="not allowlisted"),
    ):
        run_openmetadata_ingestion_container.fn(
            image="untrusted.example/image:latest",
            network="teoria_default",
            timeout_seconds=30,
        )

    docker_module.from_env.assert_not_called()


def test_kubernetes_backend_keeps_allowlist_and_does_not_require_docker_credentials(
    monkeypatch,
):
    monkeypatch.setenv("TEORIA_OPENMETADATA_INGESTION_BACKEND", "kubernetes")
    monkeypatch.setenv(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE", "registry/ingestion:approved"
    )
    monkeypatch.delenv("OPENMETADATA_INGESTION_BOT_TOKEN", raising=False)
    with patch(
        "teoria_pipelines.metadata.kubernetes_job.run_ingestion_job",
        return_value={"status": "completed"},
    ) as run:
        result = run_openmetadata_ingestion_container.fn(
            image="registry/ingestion:approved", network="unused", timeout_seconds=30
        )
    assert result == {"status": "completed"}
    run.assert_called_once_with(image="registry/ingestion:approved", timeout_seconds=30)


@pytest.mark.parametrize("succeeded,failed,raises", [(1, 0, False), (0, 1, True)])
def test_kubernetes_ingestion_job_scopes_credentials_and_cleans_up(
    monkeypatch, succeeded, failed, raises
):
    from teoria_pipelines.metadata.kubernetes_job import run_ingestion_job

    api = MagicMock()
    api.read_namespaced_job_status.return_value = SimpleNamespace(
        status=SimpleNamespace(succeeded=succeeded, failed=failed)
    )
    monkeypatch.setenv("TEORIA_KUBERNETES_NAMESPACE", "teoria-test")
    module = SimpleNamespace(
        config=SimpleNamespace(load_incluster_config=MagicMock()),
        client=SimpleNamespace(BatchV1Api=MagicMock(return_value=api)),
    )
    with patch.dict("sys.modules", {"kubernetes": module}):
        if raises:
            with pytest.raises(RuntimeError, match="Job failed"):
                run_ingestion_job(
                    image="registry/ingestion:approved", timeout_seconds=30
                )
        else:
            assert (
                run_ingestion_job(
                    image="registry/ingestion:approved", timeout_seconds=30
                )["status"]
                == "completed"
            )
    namespace, body = api.create_namespaced_job.call_args.args
    assert namespace == "teoria-test"
    pod = body["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert "volumes" not in pod
    assert {e["name"] for e in pod["containers"][0]["env"]} == {
        "TEORIA_METADATA_DB_PASSWORD",
        "OPENMETADATA_INGESTION_BOT_TOKEN",
    }
    assert all("value" not in e for e in pod["containers"][0]["env"])
    api.delete_namespaced_job.assert_called_once_with(
        body["metadata"]["name"], "teoria-test", propagation_policy="Background"
    )
