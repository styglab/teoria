"""Application approvals freeze evidence-backed standard and dictionary versions."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from teoria.features.specification_processing.application_standards_service import (
    ApplicationStandardsService,
    ApplicationStandardInput,
)
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    snapshot_from_records,
)
from teoria.features.specification_processing.storage.artifact_store import (
    artifact_store,
)


class MemoryReleases:
    def __init__(self):
        self.rows = {}

    async def create(self, body):
        row = {**body, "status": "approved"}
        self.rows[str(body["release_id"])] = deepcopy(row)
        return row

    async def get(self, id):
        return deepcopy(self.rows[str(id)])


def make_service(tmp_path):
    standard = {
        "schema_version": 1,
        "version": "example",
        "definitions": [{"id": "source_literal_property", "label": "원문 속성"}],
        "bindings": [{"target_types": ["equipment"], "property_key": "source_property",
            "unit_context": "mm", "data_type": "number", "role": "requirement_candidate",
            "semantic_scope": "per_item",
            "properties": [{"property_id": "source_literal_property", "rule_kind": "source_literal"}]}],
        "classification_code": "4321150102",
    }
    snapshot = snapshot_from_records([], [], []).model_dump(mode="json")

    class Meaning:
        async def snapshot(self):
            return deepcopy(snapshot)

    class Processing:
        async def detail(self, id):
            return {
                "run": {
                    "run_id": id,
                    "mode": "standard_management",
                    "status": "partial",
                    "classification_code": "4321150102",
                    "standard_uri": "s3://example/standard.json",
                    "standard_sha256": "a" * 64,
                },
                "artifacts": [
                    {
                        "uri": "s3://example/standard.json",
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                    }
                ],
            }

    async def read(reference):
        return deepcopy(standard)

    repo = MemoryReleases()
    service = ApplicationStandardsService(
        repo, Processing(), Meaning(), read, lambda: artifact_store(tmp_path.as_uri())
    )
    request = ApplicationStandardInput(
        name="서버 적용 기준 v1",
        source_run_id="source_run",
        expected_dictionary_checksum=snapshot["checksum"],
        rationale="원문 근거와 미해결 항목 및 적용 범위를 검토함",
    )
    return service, request, snapshot


async def test_v2_profile_release_rejects_a_different_or_unpublished_ontology(tmp_path):
    from unittest.mock import AsyncMock
    from uuid import UUID
    from backend.tests.integration.test_goods_normalization_contract import example
    from teoria.features.goods_normalization.profiles.compiler import compile_package
    from teoria.features.semantic_modeling.goods_dictionary.ontology_contracts import expression_snapshot

    service, request, _ = make_service(tmp_path)
    profile, ontology, _ = example()
    package = compile_package(profile, ontology, revision_id=UUID(int=900), approval_actor='fixture:owner')
    snapshot = expression_snapshot([], [], []).model_dump(mode='json')
    service.meanings.snapshot = AsyncMock(return_value=snapshot)
    service.read_artifact = AsyncMock(return_value=package.model_dump(mode='json'))
    request = request.model_copy(update={'expected_dictionary_checksum': snapshot['checksum']})
    with pytest.raises(ValueError, match='application_ontology_version_mismatch'):
        await service.create(request, actor='fixture:owner')
    assert service.repository.rows == {}


async def test_approval_creates_immutable_paired_references_and_rejects_tampering(
    tmp_path,
):
    service, request, snapshot = make_service(tmp_path)
    release = await service.create(request, actor="reviewer:alice")
    assert release["approved_by"] == "reviewer:alice"
    assert release["standard_kind"] == "extraction_draft"
    assert release["dictionary_checksum"] == snapshot["checksum"]
    for key in ("standard_ref", "dictionary_ref"):
        assert Path(release[key]["uri"].removeprefix("file://")).is_file()
    manifest = {
        "application_release_id": str(release["release_id"]),
        "mode": "document_processing",
        "standard": release["standard_ref"],
        "dictionary_standard": release["dictionary_ref"],
        "classification_code": release["classification_code"],
        "dictionary_auto_approve": False,
        "dictionary_meaning_auto_approve": False,
    }
    assert await service.validate_execution(manifest) == manifest
    for changed in (
        {"standard": {"uri": "file:///other", "sha256": "b" * 64}},
        {"classification_code": None},
        {"dictionary_standard": None},
        {"dictionary_auto_approve": True},
    ):
        with pytest.raises(ValueError):
            await service.validate_execution({**manifest, **changed})
    snapshot["checksum"] = "b" * 64
    with pytest.raises(ValueError, match="dictionary_changed"):
        await service.create(request, actor="reviewer:bob")
    assert len(service.repository.rows) == 1


async def test_approval_rejects_changed_classification_and_failed_source(tmp_path):
    service, request, _ = make_service(tmp_path)
    original = service.processing.detail

    async def failed(id):
        result = await original(id)
        result["run"]["status"] = "failed"
        return result

    service.processing.detail = failed
    with pytest.raises(ValueError, match="not_ready"):
        await service.create(request, actor="owner")

    async def mismatch(id):
        result = await original(id)
        result["run"]["classification_code"] = None
        return result

    service.processing.detail = mismatch
    with pytest.raises(ValueError, match="classification_mismatch"):
        await service.create(request, actor="owner")


async def test_approval_http_enforces_owner_and_authenticated_actor(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.specification_processing.application_standards_router import (
        create_application_standards_router,
    )
    from teoria.settings import Settings

    service, request, _ = make_service(tmp_path)
    app = FastAPI()
    app.include_router(
        create_application_standards_router(
            service,
            AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer",
                    admin_api_token="test",
                    admin_api_actor="authenticated:owner",
                    admin_api_roles="ontology_owner",
                )
            ),
        )
    )
    client = TestClient(app)
    path = "/v1/admin/specification-processing/application-standards"
    body = request.model_dump(mode="json")
    assert client.post(path, json=body).status_code == 401
    headers = {"Authorization": "Bearer test"}
    assert (
        client.post(
            path, headers=headers, json={**body, "actor": "spoofed"}
        ).status_code
        == 422
    )
    result = client.post(path, headers=headers, json=body)
    assert result.status_code == 201
    assert result.json()["approved_by"] == "authenticated:owner"
    denied = FastAPI()
    denied.include_router(
        create_application_standards_router(
            service,
            AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer",
                    admin_api_token="test",
                    admin_api_roles="metadata_admin",
                )
            ),
        )
    )
    assert TestClient(denied).post(path, headers=headers, json=body).status_code == 403


async def test_workflow_rejects_a_tampered_release_before_calling_prefect(tmp_path):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.features.access_control.auth import AdminAuthorizer
    from teoria.features.workflow_management.admin_router import create_workflow_router
    from teoria.settings import Settings

    service, request, _ = make_service(tmp_path)
    release = await service.create(request, actor="owner")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                AssertionError("Prefect must not be called")
            )
        )
    ) as http:
        app = FastAPI()
        app.include_router(
            create_workflow_router(
                authorizer=AdminAuthorizer(Settings(admin_api_roles="metadata_admin")),
                client=http,
                prefect_url="http://prefect.invalid/api",
                prefect_auth="test:test",
                mlops_enabled=False,
                application_standards=service,
            )
        )
        response = TestClient(app).post(
            "/v1/admin/workflows/pipelines/specification-document-processing/runs",
            json={
                "idempotency_key": str(uuid4()),
                "manifest": {
                    "run_id": "test_run",
                    "mode": "document_processing",
                    "application_release_id": str(release["release_id"]),
                    "documents": [
                        {
                            "document_id": "test_doc",
                            "filename": "test.pdf",
                            "source_uri": "file:///test.pdf",
                        }
                    ],
                    "artifact_root": tmp_path.as_uri(),
                    "standard": release["standard_ref"],
                    "dictionary_standard": {
                        **release["dictionary_ref"],
                        "sha256": "f" * 64,
                    },
                    "classification_code": release["classification_code"],
                    "dictionary_auto_approve": False,
                    "dictionary_meaning_auto_approve": False,
                },
            },
        )
    assert response.status_code == 422


async def test_empty_standard_is_visible_but_cannot_be_approved_or_reexecuted(tmp_path):
    from unittest.mock import AsyncMock
    service, request, _ = make_service(tmp_path)
    empty = {'version':'empty', 'definitions':[], 'bindings':[], 'classification_code':'4321150102'}
    service.read_artifact = AsyncMock(return_value=empty)
    readiness = await service.readiness(request.source_run_id)
    assert readiness['ready'] is False and readiness['rule_count'] == 0
    assert readiness['reason'] == 'standard_has_no_application_rules'
    with pytest.raises(ValueError, match='standard_has_no_application_rules'):
        await service.create(request, actor='verified:reviewer')
    assert service.repository.rows == {} and not list(tmp_path.iterdir())
    # A historical approved row also requires a usable fixed standard at execution.
    release_id = str(uuid4())
    row = {'status':'approved','standard_kind':'extraction_draft','classification_code':'4321150102',
           'standard_ref':{'uri':'s3://example/empty.json','sha256':'a'*64},
           'dictionary_ref':{'uri':'s3://example/dictionary.json','sha256':'b'*64}}
    service.repository.rows[release_id] = row
    with pytest.raises(ValueError, match='standard_has_no_application_rules'):
        await service.validate_execution({'application_release_id':release_id,'mode':'document_processing',
            'classification_code':row['classification_code'],'standard':row['standard_ref'],
            'dictionary_standard':row['dictionary_ref']})
