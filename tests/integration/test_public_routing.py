"""Optional gateway/Ingress contract against isolated echo API and real UI images."""

import json
import os
import re

import httpx
import pytest

BASE_URL = os.getenv("TEORIA_TEST_ROUTING_BASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="isolated HTTP routing fixture required"
)


@pytest.fixture
def client():
    # TLS is self-signed only in the isolated Traefik fixture.
    with httpx.Client(
        base_url=BASE_URL, headers={"Host": "teoria.invalid"}, verify=False
    ) as value:
        yield value


def test_ui_assets_and_spa_routes(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "text/html" in home.headers["content-type"]
    asset = re.search(r'src="(/assets/[^\"]+\.js)"', home.text)[1]
    response = client.get(asset)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert client.get("/ontology/authoring/example").text == home.text
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize(
    "public,upstream",
    [
        (
            "/admin-api/v1/admin/probe?term=cpu&limit=2",
            "/v1/admin/probe?term=cpu&limit=2",
        ),
        ("/runtime-api/v1/capabilities", "/v1/capabilities"),
        ("/prefect/api/health", "/api/health"),
        ("/prefect/api/events/filter", "/api/events/filter"),
        ("/prefect/", "/prefect/"),
        ("/prefect/assets/test.js", "/prefect/assets/test.js"),
    ],
)
def test_backend_path_query_body_and_authentication_are_preserved(
    client, public, upstream
):
    response = client.post(
        public,
        headers={"Authorization": "Bearer synthetic-routing"},
        json={"value": "cpu"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == upstream
    assert data["method"] == "POST"
    headers = {key.lower(): value for key, value in data["headers"].items()}
    assert headers["authorization"] == "Bearer synthetic-routing"
    assert headers["host"] == "teoria.invalid"
    assert json.loads(data["body"]) == {"value": "cpu"}


def test_prefect_websocket_upgrade(client):
    response = client.get(
        "/prefect/api/events/out",
        headers={
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        },
    )
    assert response.status_code == 101
    assert response.headers["x-test-upstream-path"] == "/api/events/out"
    assert response.headers["sec-websocket-accept"] == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
