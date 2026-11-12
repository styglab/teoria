"""Verify image identity, path boundaries and upstream credential isolation."""

import hashlib
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from teoria.integrations.image_registry import ImageRegistryClient
from teoria.platform.access_control.auth import AdminAuthorizer
from teoria.platform.mlops.image_registry_router import create_image_registry_router
from teoria.settings import Settings


def api(handler, *, configured=True):
    app = FastAPI()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    registry = (
        ImageRegistryClient(
            client,
            url="https://images.internal",
            public_host="registry.example.com:5000",
            username="reader",
            password="registry-secret",
        )
        if configured
        else None
    )
    app.include_router(
        create_image_registry_router(
            authorizer=AdminAuthorizer(
                Settings(admin_auth_mode="bearer", admin_api_token="admin-secret")
            ),
            registry=registry,
        )
    )
    return TestClient(app)


HEADERS = {"Authorization": "Bearer admin-secret"}


def test_catalog_is_authenticated_and_never_forwards_admin_token_or_follows_links():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        assert "admin-secret" not in str(request.headers)
        assert request.url.params["n"] == "25"
        return httpx.Response(
            200,
            json={"repositories": ["teoria/admin", "models/churn"]},
            headers={"Link": '<https://attacker.invalid/steal>; rel="next"'},
        )

    with api(handler) as client:
        assert client.get("/v1/admin/image-registry/repositories").status_code == 401
        assert not calls
        response = client.get("/v1/admin/image-registry/repositories", headers=HEADERS)
    assert response.json() == {
        "items": ["teoria/admin", "models/churn"],
        "next": "models/churn",
    }
    assert len(calls) == 1


def test_manifest_returns_verified_immutable_reference():
    content = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}],
        }
    ).encode()
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    with api(
        lambda r: httpx.Response(
            200, content=content, headers={"Docker-Content-Digest": digest}
        )
    ) as client:
        response = client.get(
            "/v1/admin/image-registry/manifest",
            params={"repository": "models/churn", "reference": "v1"},
            headers=HEADERS,
        )
    assert response.status_code == 200
    assert (
        response.json()["image"] == f"registry.example.com:5000/models/churn@{digest}"
    )
    assert response.json()["platforms"] == [{"os": "linux", "architecture": "amd64"}]


@pytest.mark.parametrize("reference", ["v1", "sha256:" + "0" * 64])
def test_manifest_digest_mismatch_is_rejected(reference):
    with api(
        lambda r: httpx.Response(
            200, content=b"{}", headers={"Docker-Content-Digest": "sha256:" + "0" * 64}
        )
    ) as client:
        response = client.get(
            "/v1/admin/image-registry/manifest",
            params={"repository": "models/churn", "reference": reference},
            headers=HEADERS,
        )
    assert response.status_code == 502


@pytest.mark.parametrize(
    "path,params",
    [
        ("tags", {"repository": "../admin"}),
        ("tags", {"repository": "models//churn"}),
        ("manifest", {"repository": "models/churn", "reference": "../tags/list"}),
    ],
)
def test_invalid_paths_never_reach_registry(path, params):
    calls = []
    with api(lambda r: calls.append(r)) as client:
        response = client.get(
            "/v1/admin/image-registry/" + path, params=params, headers=HEADERS
        )
    assert response.status_code == 422
    assert calls == []


def test_registry_credentials_failure_is_not_an_admin_authentication_failure():
    with api(lambda r: httpx.Response(401, text="registry-secret")) as client:
        response = client.get("/v1/admin/image-registry/repositories", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "image_registry_auth_failed"
    assert "registry-secret" not in response.text


def test_disabled_catalog_needs_no_mlops_services():
    with api(
        lambda r: pytest.fail("unexpected network request"), configured=False
    ) as client:
        assert client.get(
            "/v1/admin/image-registry/status", headers=HEADERS
        ).json() == {"configured": False, "host": None}
        assert (
            client.get(
                "/v1/admin/image-registry/repositories", headers=HEADERS
            ).status_code
            == 503
        )


@pytest.mark.parametrize("path", ["repositories", "tags?repository=models/churn"])
def test_malformed_registry_document_returns_a_safe_error(path):
    with api(lambda r: httpx.Response(200, json=[])) as client:
        response = client.get("/v1/admin/image-registry/" + path, headers=HEADERS)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_image_registry_response"


@pytest.mark.asyncio
async def test_harbor_catalog_uses_project_reader_and_pages_without_following_links():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == '/api/v2.0/projects/models/repositories'
        assert request.url.params['sort'] == 'name'
        assert request.headers['authorization'].startswith('Basic ')
        assert request.url.params['page_size'] == '1'
        page = request.url.params['page']
        return httpx.Response(200, json=[{'name': 'models/' + ('train' if page == '1' else 'serve')}],
                              headers={'X-Total-Count': '2', 'Link': '<https://attacker.invalid/>; rel="next"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = ImageRegistryClient(client, url='https://harbor.internal', provider='harbor',
                                       project='models', username='robot$reader', password='secret')
        first = await registry.repositories(limit=1)
        assert first == {'items': ['models/train'], 'next': '2'}
        assert await registry.repositories(after=first['next'], limit=1) == {'items': ['models/serve'], 'next': None}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_harbor_token_exchange_requests_only_pull_and_preserves_manifest_identity():
    content = b'{"schemaVersion":2,"layers":[]}'
    digest = 'sha256:' + hashlib.sha256(content).hexdigest()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == '/service/token':
            assert request.headers['authorization'].startswith('Basic ')
            assert request.url.params['scope'] == 'repository:models/team/train:pull'
            return httpx.Response(200, json={'token': 'scoped-reader-token'})
        assert request.url.path == '/v2/models/team/train/manifests/v1'
        if request.headers['authorization'] == 'Bearer scoped-reader-token':
            assert 'application/vnd.oci.image.manifest.v1+json' in request.headers['accept']
            return httpx.Response(200, content=content, headers={'Docker-Content-Digest': digest})
        return httpx.Response(401, headers={'WWW-Authenticate':
            'Bearer realm="https://harbor.internal/service/token",service="harbor-registry",scope="repository:models/team/train:pull,push"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = ImageRegistryClient(client, url='https://harbor.internal', provider='harbor',
                                       username='robot$reader', password='secret')
        assert (await registry.manifest('models/team/train', 'v1'))['image'] == 'harbor.internal/models/team/train@' + digest
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('realm', [
    'https://attacker.invalid/service/token', 'http://harbor.internal/service/token',
    'https://user:password@harbor.internal/service/token',
    'https://harbor.internal/service/token?secret=value', 'https://harbor.internal/other',
])
async def test_registry_does_not_send_credentials_to_untrusted_token_endpoints(realm):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, headers={'WWW-Authenticate': f'Bearer realm="{realm}"'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = ImageRegistryClient(client, url='https://harbor.internal', username='reader', password='secret')
        with pytest.raises(ValueError, match='Untrusted registry token endpoint'):
            await registry.tags('models/train')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_harbor_catalog_rejects_repositories_outside_selected_project():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{'name': 'other/private'}]),
    )) as client:
        registry = ImageRegistryClient(client, url='https://harbor.internal', provider='harbor')
        with pytest.raises(ValueError, match='Invalid Harbor repository'):
            await registry.repositories()
