from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from teoria_pipelines.flows.openmetadata import (
    _required_environment,
    run_openmetadata_ingestion_container,
)


def test_required_environment_rejects_missing_value(monkeypatch: pytest.MonkeyPatch) -> None:
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
        "teoria-openmetadata-ingestion:1.12.6",
    )
    container = MagicMock()
    container.logs.return_value = [b"metadata synchronized\n"]
    container.wait.return_value = {"StatusCode": 0}
    client = MagicMock()
    client.containers.run.return_value = container
    docker_module = SimpleNamespace(from_env=MagicMock(return_value=client))

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.flows.openmetadata.get_run_logger") as logger,
    ):
        result = run_openmetadata_ingestion_container.fn(
            image="teoria-openmetadata-ingestion:1.12.6",
            network="teoria_default",
            timeout_seconds=30,
        )

    assert result == {
        "status": "completed",
        "status_code": 0,
        "image": "teoria-openmetadata-ingestion:1.12.6",
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
        "teoria-openmetadata-ingestion:1.12.6",
    )
    container = MagicMock()
    container.logs.return_value = []
    container.wait.return_value = {"StatusCode": 7}
    client = MagicMock()
    client.containers.run.return_value = container
    docker_module = SimpleNamespace(from_env=MagicMock(return_value=client))

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.flows.openmetadata.get_run_logger"),
        pytest.raises(RuntimeError, match="status 7"),
    ):
        run_openmetadata_ingestion_container.fn(
            image="teoria-openmetadata-ingestion:1.12.6",
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
        "teoria-openmetadata-ingestion:1.12.6",
    )
    docker_module = SimpleNamespace(from_env=MagicMock())

    with (
        patch.dict("sys.modules", {"docker": docker_module}),
        patch("teoria_pipelines.flows.openmetadata.get_run_logger"),
        pytest.raises(RuntimeError, match="not allowlisted"),
    ):
        run_openmetadata_ingestion_container.fn(
            image="untrusted.example/image:latest",
            network="teoria_default",
            timeout_seconds=30,
        )

    docker_module.from_env.assert_not_called()
