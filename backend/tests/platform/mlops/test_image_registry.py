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
