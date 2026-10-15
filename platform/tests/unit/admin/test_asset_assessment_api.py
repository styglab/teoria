from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from teoria.admin.asset_assessment_api import create_asset_assessment_router
from teoria.admin.auth import AdminAuthorizer
from teoria.settings import Settings

PATH = '/v1/admin/intelligence/asset-assessments'
HEADERS = {'Authorization': 'Bearer synthetic'}


def client(*, enabled=True, roles='metadata_admin'):
    identifier = str(uuid4())
    metadata = SimpleNamespace(get_table_by_name=AsyncMock(return_value={
        'id': identifier, 'fullyQualifiedName': 's.d.c.t', 'version': 1.0, 'columns': [{'name': 'amount'}]}))
    repository = Mock(create=Mock(return_value={'assessment_id': str(uuid4()), 'status': 'queued'}),
                      list=Mock(return_value=[]))
    authorizer = AdminAuthorizer(Settings(admin_auth_mode='bearer', admin_api_token='synthetic',
        admin_api_actor='user:authenticated', admin_api_roles=roles))
    app = FastAPI()
    app.include_router(create_asset_assessment_router(repository, metadata, authorizer, enabled=enabled, model_name='synthetic'))
    return TestClient(app), repository, metadata


def test_request_requires_auth_and_records_principal_only():
    http, repo, metadata = client()
    payload = {'table_fqn': 's.d.c.t', 'scopes': ['metadata_enrichment']}
    assert http.post(PATH, json=payload).status_code == 401
    result = http.post(PATH, json=payload, headers=HEADERS)
    assert result.status_code == 202 and result.headers['cache-control'] == 'no-store'
    assert repo.create.call_args.kwargs['actor'] == 'user:authenticated'
    assert repo.create.call_args.kwargs['target_ref']['version'] == 1.0
    assert http.post(PATH, json={**payload, 'actor': 'forged'}, headers=HEADERS).status_code == 422


def test_disabled_model_and_unknown_columns_do_not_enqueue():
    http, repo, _ = client(enabled=False)
    payload = {'table_fqn': 's.d.c.t', 'scopes': ['semantic_alignment']}
    assert http.post(PATH, json=payload, headers=HEADERS).status_code == 503
    repo.create.assert_not_called()
    http, repo, _ = client()
    assert http.post(PATH, json={**payload, 'column_names': ['missing']}, headers=HEADERS).status_code == 422
    repo.create.assert_not_called()


def test_viewer_cannot_start_and_history_requires_auth():
    http, repo, _ = client(roles='metadata_reviewer')
    assert http.post(PATH, json={'table_fqn': 's.d.c.t', 'scopes': ['metadata_enrichment']}, headers=HEADERS).status_code == 403
    assert http.get(PATH, params={'table_id': str(uuid4())}).status_code == 401
    assert http.get(PATH, params={'table_id': str(uuid4())}, headers=HEADERS).status_code == 200
