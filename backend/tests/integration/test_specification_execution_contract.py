"""The deployment credential reaches the real HTTP boundary without Admin authority."""
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from teoria.domains.goods.authoring_client import GoodsAuthoringClient
from teoria.entrypoints.admin_api import create_admin_app
from teoria.integrations.prefect.deployment import kubernetes_job_template
from teoria.integrations.prefect.deployment_manifests import load_execution_policy
from teoria.settings import Settings


def configured_app():
    return create_admin_app(settings=Settings(
        environment="test", admin_auth_mode="bearer", admin_api_token="synthetic-admin",
        specification_authoring_api_token="synthetic-workflow", legal_information_enabled=False,
        goods_authoring_enabled=True, formatid_enabled=True,
    ))


async def test_workflow_client_authenticates_against_composed_api_and_cannot_publish():
    app = configured_app()
    async with GoodsAuthoringClient(base_url="http://admin-api:8001", token="synthetic-workflow",
                                   transport=httpx.ASGITransport(app)) as client:
        session = await client.http.get("/v1/admin/auth/session")
        assert session.status_code == 200
        assert session.json()["actor"] == "service:specification-processing"
        # A permitted read reaches the owning service and reports its missing DB.
        assert (await client.http.get("/v1/admin/goods/dictionary/snapshot")).status_code == 503
        for method, path in [
            ("GET", "/v1/admin/metadata/status"),
            ("POST", "/v1/admin/ontology-authoring/versions/00000000-0000-0000-0000-000000000001/publish"),
            ("POST", "/v1/admin/goods/normalization-profiles/00000000-0000-0000-0000-000000000001/transitions"),
        ]:
            response = await client.http.request(method, path, json={})
            assert response.status_code == 403, response.text
        client.http.headers["Authorization"] = "Bearer incorrect"
        assert (await client.http.get("/v1/admin/auth/session")).status_code == 401
    # Human Admin credentials still follow their existing authentication policy.
    with TestClient(app) as client:
        session = client.get("/v1/admin/auth/session", headers={"Authorization": "Bearer synthetic-admin"})
        assert session.status_code == 200
        assert session.json()["actor"] == "system:admin"


def test_service_token_cannot_reuse_admin_credential():
    with pytest.raises(ValueError, match="distinct"):
        create_admin_app(settings=Settings(admin_auth_mode="bearer", admin_api_token="same",
                                          specification_authoring_api_token="same"))


async def test_real_prefect_template_uses_role_configuration_and_distinct_execution_images(monkeypatch):
    pytest.importorskip("prefect_kubernetes")
    root = Path(__file__).resolve().parents[3] / "backend"
    for kind, image in [("ingestion", "specification-job"), ("legal-information", "legal-job")]:
        pool = load_execution_policy(root, kind, "kubernetes")["pools"][0]
        monkeypatch.setenv("TEORIA_PIPELINE_JOB_IMAGE", "registry.example/teoria/" + image + ":" + "a" * 40)
        monkeypatch.setenv("TEORIA_ADMIN_API_TOKEN", "must-not-leak")
        template = kubernetes_job_template(root, secret_name=pool["job_secret"],
            configuration_secret=pool.get("configuration_secret"), codex_secret=pool.get("codex_secret"))
        from unittest.mock import AsyncMock
        from prefect.client.schemas.objects import FlowRun
        from prefect_kubernetes.worker import KubernetesWorkerJobConfiguration
        configuration = await KubernetesWorkerJobConfiguration.from_template_and_values(template, {}, client=AsyncMock())
        configuration.prepare_for_flow_run(FlowRun(flow_id="00000000-0000-0000-0000-000000000001"))
        pod = configuration.job_manifest["spec"]["template"]["spec"]
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["automountServiceAccountToken"] is False
        references = {item["secretRef"]["name"] for item in pod["containers"][0]["envFrom"]}
        if kind == "ingestion":
            assert references == {"teoria-pipeline-secrets", "specification-processing"}
            assert pod["volumes"][0]["secret"]["secretName"] == "specification-codex"
        else:
            assert references == {"teoria-legal-information-secrets"}
            assert not pod.get("volumes")
        assert "must-not-leak" not in str(template)
        assert template["variables"]["properties"]["image"]["default"].split("/")[-1].startswith(image + ":")


async def test_read_only_activation_check_uses_service_auth_and_signed_bucket_probe(monkeypatch, tmp_path):
    from teoria.domains.goods.data_processing.preflight import verify
    auth = tmp_path / 'auth.json'
    auth.write_text('{"OPENAI_API_KEY":"synthetic-model"}')
    for name, value in {
        'TEORIA_CODEX_AUTH_PATH': str(auth),
        'TEORIA_SPECIFICATION_AUTHORING_API_URL': 'http://admin-api:8001',
        'TEORIA_SPECIFICATION_AUTHORING_API_TOKEN': 'synthetic-workflow',
        'TEORIA_SPECIFICATION_ARTIFACT_ROOT': 's3://teoria-artifacts/production',
        'TEORIA_SPECIFICATION_S3_ENDPOINT': 'http://minio:9000',
        'TEORIA_SPECIFICATION_S3_ACCESS_KEY': 'synthetic-access',
        'TEORIA_SPECIFICATION_S3_SECRET_KEY': 'synthetic-storage-secret',
    }.items():
        monkeypatch.setenv(name, value)
    calls = []
    def bucket(request):
        calls.append(request)
        assert request.method == 'HEAD'
        assert str(request.url) == 'http://minio:9000/teoria-artifacts'
        assert request.headers['Authorization'].startswith('AWS4-HMAC-SHA256 ')
        assert 'synthetic-storage-secret' not in str(request.headers)
        return httpx.Response(200)
    await verify(authoring_transport=httpx.ASGITransport(configured_app()),
                 storage_transport=httpx.MockTransport(bucket))
    assert len(calls) == 1
    with pytest.raises(httpx.HTTPStatusError):
        await verify(authoring_transport=httpx.ASGITransport(configured_app()),
                     storage_transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    monkeypatch.setenv('TEORIA_SPECIFICATION_AUTHORING_API_TOKEN', 'synthetic-admin')
    with pytest.raises(ValueError, match='dedicated service'):
        await verify(authoring_transport=httpx.ASGITransport(configured_app()),
                     storage_transport=httpx.MockTransport(bucket))
