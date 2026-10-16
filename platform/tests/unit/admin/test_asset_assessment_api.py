from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.admin.asset_assessment_api import create_asset_assessment_router
from teoria.admin.auth import AdminAuthorizer
from teoria.settings import Settings

PATH = "/v1/admin/intelligence/asset-assessments"
HEADERS = {"Authorization": "Bearer synthetic"}


def client(*, enabled=True, roles="metadata_admin"):
    identifier = str(uuid4())
    metadata = SimpleNamespace(
        get_table_by_name=AsyncMock(
            return_value={
                "id": identifier,
                "fullyQualifiedName": "s.d.c.t",
                "version": 1.0,
                "columns": [{"name": "amount"}],
            }
        )
    )
    record = {
        "assessment_id": str(uuid4()),
        "status": "queued",
        "target_ref": {
            "system": "openmetadata",
            "entity_id": identifier,
            "entity_type": "table",
            "fully_qualified_name": "s.d.c.t",
            "version": 1.0,
        },
        "scopes": ["metadata_enrichment"],
        "column_names": [],
        "assessment_date": "2026-10-16",
        "disclosure_context": "public_release",
        "requested_by": "user:authenticated",
        "model_name": "synthetic",
        "policy_version": "asset_assessment_v1",
        "attempts": 0,
        "created_at": "2026-10-16T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "lease_until": None,
        "error_code": None,
        "findings": [],
        "suggestion_ids": [],
    }
    repository = Mock(
        create=AsyncMock(return_value=record),
        list=AsyncMock(return_value=[]),
        get=AsyncMock(return_value=record),
    )
    authorizer = AdminAuthorizer(
        Settings(
            admin_auth_mode="bearer",
            admin_api_token="synthetic",
            admin_api_actor="user:authenticated",
            admin_api_roles=roles,
        )
    )
    app = FastAPI()
    app.include_router(
        create_asset_assessment_router(
            repository, metadata, authorizer, enabled=enabled, model_name="synthetic"
        )
    )
    return TestClient(app), repository, metadata


def test_request_requires_auth_and_records_principal_only():
    http, repo, metadata = client()
    payload = {"table_fqn": "s.d.c.t", "scopes": ["metadata_enrichment"]}
    assert http.post(PATH, json=payload).status_code == 401
    result = http.post(PATH, json=payload, headers=HEADERS)
    assert result.status_code == 202 and result.headers["cache-control"] == "no-store"
    assert repo.create.call_args.kwargs["actor"] == "user:authenticated"
    assert repo.create.call_args.kwargs["target_ref"]["version"] == 1.0
    assert (
        http.post(
            PATH, json={**payload, "actor": "forged"}, headers=HEADERS
        ).status_code
        == 422
    )


def test_disabled_model_and_unknown_columns_do_not_enqueue():
    http, repo, _ = client(enabled=False)
    payload = {"table_fqn": "s.d.c.t", "scopes": ["semantic_alignment"]}
    assert http.post(PATH, json=payload, headers=HEADERS).status_code == 503
    repo.create.assert_not_called()
    http, repo, _ = client()
    assert (
        http.post(
            PATH, json={**payload, "column_names": ["missing"]}, headers=HEADERS
        ).status_code
        == 422
    )
    repo.create.assert_not_called()


def test_viewer_cannot_start_and_history_requires_auth():
    http, repo, _ = client(roles="metadata_reviewer")
    assert (
        http.post(
            PATH,
            json={"table_fqn": "s.d.c.t", "scopes": ["metadata_enrichment"]},
            headers=HEADERS,
        ).status_code
        == 403
    )
    assert http.get(PATH, params={"table_id": str(uuid4())}).status_code == 401
    assert (
        http.get(PATH, params={"table_id": str(uuid4())}, headers=HEADERS).status_code
        == 200
    )


def test_assessment_responses_have_one_contract_and_hide_internal_keys():
    http, repo, _ = client()
    record = repo.create.return_value
    record.update(claim_token="internal-claim", request_key="internal-deduplication")
    record["findings"] = [
        {
            "scope": "disclosure_assessment",
            "summary": "검토 필요",
            "legal_applicability_confirmed": False,
            "evidence": [
                {
                    "evidence_type": "law_snapshot",
                    "source_ref": "test://law",
                    "provenance": {"effective_date": "2026-01-01"},
                }
            ],
        }
    ]
    repo.list.return_value = [record]
    payload = {"table_fqn": "s.d.c.t", "scopes": ["metadata_enrichment"]}
    created = http.post(PATH, json=payload, headers=HEADERS).json()
    fetched = http.get(f"{PATH}/{record['assessment_id']}", headers=HEADERS).json()
    listed = http.get(PATH, params={"table_id": str(uuid4())}, headers=HEADERS).json()[
        "items"
    ][0]
    assert created == fetched == listed
    assert "claim_token" not in created and "request_key" not in created
    assert created["findings"][0]["legal_applicability_confirmed"] is False
    schemas = http.get("/openapi.json").json()["components"]["schemas"]
    assert "claim_token" not in schemas["AssessmentResponse"]["properties"]
    assert "scope" in schemas["AssessmentFindingResponse"]["properties"]
