from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.features.access_control.auth import AdminAuthorizer
from teoria.features.semantic_modeling.ontology.admin_router import (
    create_ontology_authoring_router,
)
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
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
    repository = Mock(spec=OntologyAuthoringService)
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
    repository = Mock(spec=OntologyAuthoringService)
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


def test_publication_read_is_authenticated_and_independent_of_goods_dictionary():
    from teoria.features.semantic_modeling.ontology.publication_contracts import publication_checksum
    identifier = uuid4()
    content = {'namespace':'test', 'version':'1', 'objects':[], 'relationships':[]}
    repository = Mock(spec=OntologyAuthoringService)
    repository.publication.return_value = {
        'ontology': {'version_id':str(identifier), 'namespace':'test', 'version':'1',
                     'checksum':publication_checksum(content)}, 'content':content}
    app = FastAPI()
    app.include_router(create_ontology_authoring_router(repository, AdminAuthorizer(Settings(
        admin_auth_mode='bearer', admin_api_token='synthetic-token',
        admin_api_actor='service:reader', admin_api_roles='ontology_owner'))))
    client = TestClient(app)
    path = f'/v1/admin/ontology-authoring/versions/{identifier}/publication'
    assert client.get(path).status_code == 401
    repository.publication.assert_not_awaited()
    response = client.get(path, headers={'Authorization':'Bearer synthetic-token'})
    assert response.status_code == 200
    repository.publication.assert_awaited_once_with(identifier)
    repository.publication.side_effect = KeyError('unpublished')
    assert client.get(path, headers={'Authorization':'Bearer synthetic-token'}).status_code == 404
