import hashlib
import os
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.specification_processing.workspace_router import (
    create_processing_workspace_router,
)
from teoria.settings import Settings

HEADERS = {"Authorization": "Bearer synthetic-test-token"}


class Repository:
    def __init__(self, reference=None):
        self.reference = reference

    async def runs(self, offset, limit):
        return {"items": [{"run_id": "test_run"}], "total": 1}

    async def detail(self, run_id):
        if run_id != "test_run":
            return None
        return {
            "run": {"run_id": run_id},
            "documents": [],
            "artifacts": [self.reference] if self.reference else [],
        }


def api(tmp_path, *, roles="metadata_admin", reference=None, enabled=True):
    app = FastAPI()
    app.include_router(
        create_processing_workspace_router(
            authorizer=AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer",
                    admin_api_token="synthetic-test-token",
                    admin_api_actor="operator:verified",
                    admin_api_roles=roles,
                )
            ),
            database_url=None,
            input_root=tmp_path / "inputs",
            artifact_root=tmp_path / "artifacts",
            object_root=os.getenv('TEORIA_SPECIFICATION_ARTIFACT_ROOT',(tmp_path/'artifacts').as_uri()),
            repository=Repository(reference),
            uploads_enabled=enabled,
        )
    )
    return TestClient(app)


def test_upload_is_authenticated_bounded_and_records_audited_actor(tmp_path, caplog):
    with api(tmp_path) as client, caplog.at_level("INFO"):
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=sample.pdf",
                content=b"%PDF-synthetic",
            ).status_code
            == 401
        )
        result = client.post(
            "/v1/admin/specification-processing/documents?filename=sample.pdf",
            content=b"%PDF-synthetic",
            headers=HEADERS,
        )
    assert result.status_code == 201
    document = result.json()
    assert document["sha256"] == hashlib.sha256(b"%PDF-synthetic").hexdigest()
    assert (
        Path(document["source_uri"].removeprefix("file://")).read_bytes()
        == b"%PDF-synthetic"
    )
    assert (
        "operator:verified" in caplog.text and "synthetic-test-token" not in caplog.text
    )


def test_upload_rejects_traversal_empty_file_and_readonly_roles(tmp_path):
    with api(tmp_path) as client:
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=../bad.pdf",
                content=b"x",
                headers=HEADERS,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=bad.sh",
                content=b"x",
                headers=HEADERS,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=empty.pdf",
                content=b"",
                headers=HEADERS,
            ).status_code
            == 422
        )
    assert not list((tmp_path / "inputs").glob("*"))
    with api(tmp_path, roles="metadata_reviewer") as client:
        assert (
            client.get(
                "/v1/admin/specification-processing/runs", headers=HEADERS
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=sample.pdf",
                content=b"x",
                headers=HEADERS,
            ).status_code
            == 403
        )


def test_upload_requires_explicit_worker_storage_configuration(tmp_path):
    with api(tmp_path, enabled=False) as client:
        assert (
            client.get(
                "/v1/admin/specification-processing/status", headers=HEADERS
            ).json()["uploads_enabled"]
            is False
        )
        assert (
            client.post(
                "/v1/admin/specification-processing/documents?filename=sample.pdf",
                content=b"x",
                headers=HEADERS,
            ).status_code
            == 503
        )


def test_artifact_preview_requires_owned_reference_and_verified_checksum(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "result.json"
    path.write_bytes(b'{"documents": []}')
    ref = {
        "key": "result.json",
        "uri": path.as_uri(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }
    with api(tmp_path, reference=ref) as client:
        assert client.get(
            "/v1/admin/specification-processing/runs/test_run/artifact?key=result.json",
            headers=HEADERS,
        ).json() == {"documents": []}
        assert (
            client.get(
                "/v1/admin/specification-processing/runs/test_run/artifact?key=unknown",
                headers=HEADERS,
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/v1/admin/specification-processing/runs/missing", headers=HEADERS
            ).status_code
            == 404
        )
    path.write_bytes(b"{}")
    with api(tmp_path, reference=ref) as client:
        assert (
            client.get(
                "/v1/admin/specification-processing/runs/test_run/artifact?key=result.json",
                headers=HEADERS,
            ).status_code
            == 409
        )


def test_artifact_cannot_escape_storage_via_symlink(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    path = root / "link.json"
    path.symlink_to(outside)
    ref = {
        "key": "link.json",
        "uri": path.as_uri(),
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "size_bytes": 2,
    }
    with api(tmp_path, reference=ref) as client:
        assert (
            client.get(
                "/v1/admin/specification-processing/runs/test_run/artifact?key=link.json",
                headers=HEADERS,
            ).status_code
            == 404
        )


def test_minio_upload_and_preview_do_not_need_local_files(tmp_path,monkeypatch):
    from contextlib import asynccontextmanager
    import teoria.features.specification_processing.workspace_router as router
    from teoria.features.specification_processing.storage.artifact_store import artifact_store
    objects={}
    def handler(request):
        if request.method=='PUT':objects[request.url.path]=request.content;return httpx.Response(200)
        return httpx.Response(200,content=objects[request.url.path]) if request.url.path in objects else httpx.Response(404)
    @asynccontextmanager
    async def factory(root):
        async with artifact_store(root,transport=httpx.MockTransport(handler)) as store:yield store
    monkeypatch.setenv('TEORIA_SPECIFICATION_ARTIFACT_ROOT','s3://teoria-artifacts')
    monkeypatch.setenv('TEORIA_SPECIFICATION_S3_ENDPOINT','http://minio:9000')
    monkeypatch.setenv('TEORIA_SPECIFICATION_S3_ACCESS_KEY','fixture')
    monkeypatch.setenv('TEORIA_SPECIFICATION_S3_SECRET_KEY','fixture')
    monkeypatch.setattr(router,'artifact_store',factory)
    with api(tmp_path) as client:
        response=client.post('/v1/admin/specification-processing/documents?filename=doc.pdf',headers=HEADERS,content=b'%PDF-example')
    assert response.status_code==201
    assert response.json()['source_uri'].startswith('s3://teoria-artifacts/specification_inputs/')
    assert not (tmp_path/'inputs').exists()
    raw=b'{"documents":[]}'
    objects['/teoria-artifacts/specification_processing/test/result.json']=raw
    ref={'key':'result.json','uri':'s3://teoria-artifacts/specification_processing/test/result.json','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}
    with api(tmp_path,reference=ref) as client:
        assert client.get('/v1/admin/specification-processing/runs/test_run/artifact?key=result.json',headers=HEADERS).json()=={'documents':[]}
    ref['uri']='s3://another-bucket/result.json'
    with api(tmp_path,reference=ref) as client:
        assert client.get('/v1/admin/specification-processing/runs/test_run/artifact?key=result.json',headers=HEADERS).status_code==404
