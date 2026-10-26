from unittest.mock import AsyncMock
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.settings import Settings
from teoria.features.goods_normalization.profiles.admin_router import (
    create_normalization_profile_router,
)


def client(repo):
    app = FastAPI()
    settings = Settings(
        admin_auth_mode="bearer",
        admin_api_token="test-token",
        admin_api_actor="principal:test",
        admin_api_roles="ontology_owner",
    )
    app.include_router(
        create_normalization_profile_router(repo, AdminAuthorizer(settings))
    )
    return TestClient(app)


def test_profile_review_uses_authenticated_actor_and_rejects_body_actor():
    repo = AsyncMock()
    repo.transition.return_value = {"status": "approved"}
    http = client(repo)
    path = "/v1/admin/goods/normalization-profiles/00000000-0000-0000-0000-000000000001/transitions"
    assert http.post(path, json={"action": "approve"}).status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    assert (
        http.post(
            path, headers=headers, json={"action": "approve", "actor": "forged"}
        ).status_code
        == 422
    )
    assert (
        http.post(
            path, headers=headers, json={"action": "approve", "comment": "checked"}
        ).status_code
        == 200
    )
    repo.transition.assert_awaited_once_with(
        UUID(int=1), action="approve", comment="checked", actor="principal:test"
    )


def test_unapproved_profile_is_not_exportable():
    repo = AsyncMock()
    repo.export.side_effect = ValueError("only approved profiles can be exported")
    response = client(repo).get(
        "/v1/admin/goods/normalization-profiles/00000000-0000-0000-0000-000000000001/package",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 409


def candidate_request():
    from teoria.features.goods_normalization.contracts import checksum

    body = {
        "schema_version": 1,
        "artifact_kind": "goods_meaning_candidates",
        "classification_code": "4321150102",
        "ontology": {
            "version_id": str(UUID(int=2)),
            "namespace": "test",
            "version": "1",
            "checksum": "a" * 64,
        },
        "groups": [],
    }
    return {
        "base_revision_id": str(UUID(int=1)),
        "bundles": [{**body, "checksum": checksum(body)}],
    }


def test_candidate_routes_require_authentication_and_validate_input_integrity():
    repo = AsyncMock()
    repo.candidate_proposals.return_value = {"groups": [], "published": False}
    http = client(repo)
    path = "/v1/admin/goods/normalization-profiles/candidate-proposals"
    payload = candidate_request()
    headers = {"Authorization": "Bearer test-token"}
    assert http.post(path, json=payload).status_code == 401
    assert http.post(path, headers=headers, json=payload).status_code == 200
    repo.candidate_proposals.assert_awaited_once()
    payload["bundles"][0]["classification_code"] = "4321150701"
    assert http.post(path, headers=headers, json=payload).status_code == 422
    assert repo.candidate_proposals.await_count == 1


def test_candidate_draft_records_principal_and_never_auto_approves():
    repo = AsyncMock()
    repo.create_from_candidates.return_value = {"status": "draft"}
    http = client(repo)
    payload = candidate_request()
    payload.update(
        version="next",
        selections=[{"group_id": "b" * 64, "concept_id": str(UUID(int=3))}],
    )
    path = "/v1/admin/goods/normalization-profiles/from-candidates"
    headers = {"Authorization": "Bearer test-token"}
    assert (
        http.post(
            path, headers=headers, json={**payload, "actor": "forged"}
        ).status_code
        == 422
    )
    assert http.post(path, headers=headers, json=payload).json()["status"] == "draft"
    assert repo.create_from_candidates.await_args.kwargs["actor"] == "principal:test"
    assert repo.create_from_candidates.await_args.kwargs["version"] == "next"
    repo.transition.assert_not_called()
