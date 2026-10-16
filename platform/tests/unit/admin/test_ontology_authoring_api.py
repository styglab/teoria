from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.admin.auth import AdminAuthorizer
from teoria.admin.ontology_authoring_api import create_ontology_authoring_router
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.settings import Settings


@pytest.mark.parametrize(
    "error,status,code",
    [
        (KeyError("missing"), 404, "ontology_not_found"),
        (
            ValueError("Only draft versions may change"),
            409,
            "invalid_ontology_operation",
        ),
    ],
)
def test_async_authoring_errors_keep_http_contract(error, status, code):
    repository = Mock(spec=OntologyAuthoringRepository)
    repository.get_version.side_effect = error
    identifier = uuid4()
    app = FastAPI()
    app.include_router(
        create_ontology_authoring_router(repository, AdminAuthorizer(Settings()))
    )
    response = TestClient(app).get(
        f"/v1/admin/ontology-authoring/versions/{identifier}"
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    repository.get_version.assert_awaited_once_with(identifier)


def test_draft_creation_waits_for_repository_and_uses_authenticated_actor():
    repository = Mock(spec=OntologyAuthoringRepository)
    repository.create_draft.return_value = {"status": "draft", "version": "2.0"}
    app = FastAPI()
    app.include_router(
        create_ontology_authoring_router(
            repository,
            AdminAuthorizer(
                Settings(
                    admin_auth_mode="bearer",
                    admin_api_token="synthetic-token",
                    admin_api_actor="user:owner",
                    admin_api_roles="ontology_owner",
                )
            ),
        )
    )
    client = TestClient(app)
    path = "/v1/admin/ontology-authoring/ontologies/test/versions"
    assert client.post(path, json={"version": "2.0"}).status_code == 401
    response = client.post(
        path,
        json={"version": "2.0"},
        headers={
            "Authorization": "Bearer synthetic-token",
        },
    )
    assert response.status_code == 201 and response.json()["status"] == "draft"
    repository.create_draft.assert_awaited_once_with(
        "test",
        version="2.0",
        based_on_version_id=None,
        actor="user:owner",
    )
