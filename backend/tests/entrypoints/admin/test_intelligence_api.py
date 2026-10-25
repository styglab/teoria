from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.metadata_management.intelligence.admin_api import create_intelligence_router
from teoria.features.metadata_management.intelligence.suggestions.execution import SuggestionApplicationError
from teoria.settings import Settings
from teoria.features.metadata_management.intelligence.suggestions.service import SuggestionService

IDENTIFIER = UUID("00000000-0000-4000-8000-000000000001")
HEADERS = {"Authorization": "Bearer synthetic-test-token"}


def client(repository, service, *, roles="metadata_reviewer"):
    app = FastAPI()
    authorizer = AdminAuthorizer(
        Settings(
            admin_auth_mode="bearer",
            admin_api_token="synthetic-test-token",
            admin_api_actor="user:reviewer",
            admin_api_roles=roles,
        )
    )
    resolved_service = SuggestionService(
        repository, getattr(service, "metadata_client", None)
    )
    for method in ("review_and_apply", "reconcile_application"):
        if service is not None and hasattr(service, method):
            setattr(resolved_service, method, getattr(service, method))
    app.include_router(create_intelligence_router(resolved_service, authorizer))
    return TestClient(app)


def test_asset_page_uses_exact_authoritative_refs_and_server_filters():
    repo = Mock()
    repo.list_page = AsyncMock(return_value={"items": [], "next_cursor": None})
    metadata = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "id": str(IDENTIFIER),
                "fullyQualifiedName": "svc.db.schema.table",
                "columns": [{"fullyQualifiedName": "svc.db.schema.table.column"}],
                "tags": [{"source": "Glossary", "tagFQN": "Business.Term"}],
            }
        )
    )
    http = client(repo, SimpleNamespace(metadata_client=metadata))
    path = f"/v1/admin/intelligence/suggestions?table_id={IDENTIFIER}&status=pending&after=cursor"
    assert http.get(path).status_code == 401
    response = http.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    values = repo.list_page.call_args.kwargs
    assert values["status"] == "pending" and values["after"] == "cursor"
    assert "openmetadata://column/svc.db.schema.table.column" in values["target_refs"]
    assert "openmetadata://glossary_term/Business.Term" in values["target_refs"]
    assert "svc.db.schema.table_neighbor" not in values["target_refs"]


def test_asset_source_failure_does_not_fall_back_to_global_suggestions():
    repo = Mock()
    metadata = SimpleNamespace(get=AsyncMock(return_value={"id": "another-table"}))
    result = client(repo, SimpleNamespace(metadata_client=metadata)).get(
        f"/v1/admin/intelligence/suggestions?table_id={IDENTIFIER}",
        headers=HEADERS,
    )
    assert result.status_code == 503
    repo.list_page.assert_not_called()


@pytest.mark.parametrize(
    "status", ["pending", "rejected", "changes_requested", "applied"]
)
def test_retry_cannot_approve_unapproved_or_finished_suggestions(status):
    repo = Mock(
        get=AsyncMock(return_value={"status": status, "suggestion_type": "description"})
    )
    service = SimpleNamespace(review_and_apply=AsyncMock())
    result = client(repo, service).post(
        f"/v1/admin/intelligence/suggestions/{IDENTIFIER}/applications/retry",
        headers=HEADERS,
    )
    assert result.status_code == 409
    service.review_and_apply.assert_not_awaited()


def test_retry_preserves_principal_and_existing_execution_guard():
    repo = Mock(
        get=AsyncMock(
            return_value={"status": "failed", "suggestion_type": "description"}
        )
    )
    service = SimpleNamespace(
        review_and_apply=AsyncMock(
            side_effect=SuggestionApplicationError(
                "Verify existing effect",
                code="application_reconciliation_required",
            )
        )
    )
    http = client(repo, service)
    path = f"/v1/admin/intelligence/suggestions/{IDENTIFIER}/applications/retry"
    assert http.post(path).status_code == 401
    assert (
        http.post(path, headers=HEADERS).json()["detail"]["code"]
        == "application_reconciliation_required"
    )
    service.review_and_apply.assert_awaited_once_with(
        IDENTIFIER,
        decision="approve",
        reviewer="user:reviewer",
        comment=None,
    )


def test_ontology_retry_requires_owner_role():
    repo = Mock(
        get=AsyncMock(
            return_value={"status": "failed", "suggestion_type": "ontology_change"}
        )
    )
    service = SimpleNamespace(review_and_apply=AsyncMock())
    result = client(repo, service).post(
        f"/v1/admin/intelligence/suggestions/{IDENTIFIER}/applications/retry",
        headers=HEADERS,
    )
    assert result.status_code == 403
    service.review_and_apply.assert_not_awaited()


def test_invalid_cursor_is_reported_as_validation_error():
    repo = Mock(
        list_page=AsyncMock(side_effect=ValueError("Invalid suggestion cursor"))
    )
    response = client(repo, None).get(
        "/v1/admin/intelligence/suggestions?after=invalid", headers=HEADERS
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_suggestion_cursor"


def test_application_history_requires_auth_and_preserves_pagination():
    repo = Mock(
        application_attempts=AsyncMock(return_value={"items": [], "next_cursor": None})
    )
    http = client(repo, None)
    path = f"/v1/admin/intelligence/suggestions/{IDENTIFIER}/applications/attempts?limit=2&after={IDENTIFIER}"
    assert http.get(path).status_code == 401
    response = http.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    repo.application_attempts.assert_called_once_with(
        IDENTIFIER, limit=2, after=IDENTIFIER
    )
    repo.application_attempts.side_effect = KeyError("missing")
    assert http.get(path, headers=HEADERS).status_code == 404
    repo.application_attempts.side_effect = ValueError("foreign cursor")
    assert http.get(path, headers=HEADERS).status_code == 422


def test_comparison_reads_current_target_without_writing_or_exposing_it_in_db():
    repo = Mock(
        get=AsyncMock(return_value={"proposed_value": {"table_id": str(IDENTIFIER)}})
    )
    metadata = SimpleNamespace(
        get=AsyncMock(
            return_value={
                "id": str(IDENTIFIER),
                "fullyQualifiedName": "svc.db.schema.table",
                "description": "Live description",
                "version": 2.0,
            }
        )
    )
    http = client(repo, SimpleNamespace(metadata_client=metadata))
    path = f"/v1/admin/intelligence/suggestions/{IDENTIFIER}/target"
    assert http.get(path).status_code == 401
    response = http.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["description"] == "Live description"
    assert response.json()["reference"]["version"] == 2.0
    metadata.get.assert_awaited_once_with(
        f"v1/tables/{IDENTIFIER}", params={"fields": "columns,tags"}
    )
    assert [call[0] for call in repo.method_calls] == ["get"]
    metadata.get.return_value = {"id": "wrong-table"}
    assert http.get(path, headers=HEADERS).status_code == 503
    repo.get.return_value = {"proposed_value": {}}
    assert http.get(path, headers=HEADERS).status_code == 422
