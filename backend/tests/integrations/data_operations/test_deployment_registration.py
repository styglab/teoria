from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from prefect.client.schemas.objects import FlowRun
from prefect.settings import PREFECT_API_AUTH_STRING, temporary_settings
from teoria.integrations.prefect import deployment
from teoria.integrations.prefect.deployment_manifests import load_deployment_manifest

ROOT = (Path(__file__).resolve().parents[4])


@pytest.mark.parametrize("kind", ["ingestion", "legal-information", "metadata"])
def test_register_cli_returns_success_after_synchronous_registration(monkeypatch, kind):
    from teoria.entrypoints.pipeline_cli import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "teoria-pipelines",
            "register",
            "--backend",
            "process",
            "--kind",
            kind,
            "--pipelines",
            "backend",
        ],
    )
    with patch.object(
        deployment, "register_deployments", return_value=None
    ) as register:
        assert main() == 0
    register.assert_called_once_with(Path("backend"), backend="process", kind=kind)


@pytest.mark.asyncio
async def test_job_resources_and_secrets_survive_prefect_render(monkeypatch):
    pytest.importorskip("prefect_kubernetes")
    from prefect_kubernetes.worker import KubernetesWorkerJobConfiguration

    monkeypatch.setenv(
        "TEORIA_PIPELINE_JOB_IMAGE", "ghcr.io/example/teoria/pipelines:commit"
    )
    with temporary_settings({PREFECT_API_AUTH_STRING: "dispatcher:private"}):
        config = await KubernetesWorkerJobConfiguration.from_template_and_values(
            deployment.kubernetes_job_template(),
            {"cpu_request": "500m", "memory_limit": "3Gi"},
            client=AsyncMock(),
        )
        config.prepare_for_flow_run(
            FlowRun(flow_id="00000000-0000-0000-0000-000000000001")
        )
    pod = config.job_manifest["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert config.namespace == "teoria-pipelines"
    assert container["image"] == "ghcr.io/example/teoria/pipelines:commit"
    assert container["resources"] == {
        "requests": {"cpu": "500m", "memory": "2Gi"},
        "limits": {"cpu": "2", "memory": "3Gi"},
    }
    assert container["envFrom"] == [{"secretRef": {"name": "teoria-pipeline-secrets"}}]
    assert "dispatcher:private" not in str(config.job_manifest)
    assert "PREFECT_API_AUTH_STRING" not in {item["name"] for item in container["env"]}
    assert pod["automountServiceAccountToken"] is False
    assert pod["imagePullSecrets"] == [{"name": "teoria-registry"}]


@pytest.mark.parametrize("backend", ["process", "kubernetes"])
@pytest.mark.parametrize("kind", ["ingestion", "legal-information", "metadata"])
def test_registration_preserves_shared_flow_contract(monkeypatch, backend, kind):
    original = load_deployment_manifest(ROOT / "backend", kind, backend)
    monkeypatch.setenv(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE", "ghcr.io/example/ingestion:test"
    )
    registered = []

    def capture(command, **kwargs):
        registered.append(yaml.safe_load(Path(command[-1]).read_text()))

    pool = "teoria-specification-k3s" if backend == "kubernetes" else "teoria-specification"
    if kind == "legal-information":
        pool = "teoria-legal-information-k3s" if backend == "kubernetes" else "teoria-legal-information"
    if kind == "metadata":
        pool = "teoria-metadata"
    with (
        patch.object(deployment, "configure_pool", new=AsyncMock(return_value=pool)),
        patch.object(deployment.subprocess, "run", side_effect=capture),
        patch("prefect.client.orchestration.get_client"),
    ):
        deployment.register_deployments(ROOT / "backend", backend=backend, kind=kind)
    for before, after in zip(
        original["deployments"], registered[0]["deployments"], strict=True
    ):
        assert after["work_pool"]["name"] == pool
        after["work_pool"]["name"] = before["work_pool"]["name"]
        if kind == "metadata":
            assert after["parameters"]["image"] == "ghcr.io/example/ingestion:test"
            after["parameters"]["image"] = before["parameters"]["image"]
        assert after == before
    assert load_deployment_manifest(ROOT / "backend", kind, backend) == original


@pytest.mark.parametrize("total", ["0", "-1"])
@pytest.mark.asyncio
async def test_invalid_concurrency_is_rejected_before_pool_mutation(
    monkeypatch, total
):
    monkeypatch.setenv("TEORIA_PIPELINE_CONCURRENCY", total)
    client = AsyncMock()
    with pytest.raises(ValueError):
        await deployment.configure_pool(client, backend="process", kind="ingestion")
    client.create_work_pool.assert_not_called()


@pytest.mark.asyncio
async def test_legal_kubernetes_jobs_use_only_the_dedicated_secret(monkeypatch):
    pytest.importorskip("prefect_kubernetes")
    monkeypatch.setenv("TEORIA_PIPELINE_JOB_IMAGE", "ghcr.io/example/law-worker:test")
    client = AsyncMock()
    client.read_work_pool.return_value.type = 'kubernetes'
    pool = await deployment.configure_pool(client, backend='kubernetes', kind='legal-information')
    assert pool == 'teoria-legal-information-k3s'
    update = client.update_work_pool.call_args.args[1]
    pod = update.base_job_template['job_configuration']['job_manifest']['spec']['template']['spec']
    assert pod['containers'][0]['envFrom'] == [{'secretRef': {'name': 'teoria-legal-information-secrets'}}]
    assert update.concurrency_limit == 1
