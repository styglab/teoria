import gzip
import json

from fastapi.testclient import TestClient

from teoria.config import Settings
from teoria.policy.control_plane import create_policy_control_plane_app


class Repository:
    def __init__(self):
        self.decisions = []
        self.status = None

    def record_decisions(self, events):
        self.decisions.extend(events)

    def record_status(self, status):
        self.status = status


def test_control_plane_serves_bundle_and_accepts_gzipped_telemetry(tmp_path) -> None:
    bundle = tmp_path / "teoria.tar.gz"
    bundle.write_bytes(b"signed-bundle")
    repository = Repository()
    client = TestClient(create_policy_control_plane_app(
        settings=Settings(
            opa_control_plane_token="control-token",
            opa_bundle_path=bundle,
        ),
        repository=repository,
    ))
    headers = {"Authorization": "Bearer control-token"}

    response = client.get("/bundles/teoria.tar.gz", headers=headers)
    assert response.content == b"signed-bundle"

    events = [{"decision_id": "decision-1", "result": {"allow": True}}]
    response = client.post(
        "/logs",
        headers={**headers, "Content-Encoding": "gzip"},
        content=gzip.compress(json.dumps(events).encode()),
    )
    assert response.status_code == 204
    assert repository.decisions == events

    response = client.post(
        "/status", headers=headers, json={"labels": {"id": "opa-1"}}
    )
    assert response.status_code == 204
    assert repository.status["labels"]["id"] == "opa-1"


def test_control_plane_requires_bearer_token(tmp_path) -> None:
    bundle = tmp_path / "teoria.tar.gz"
    bundle.write_bytes(b"bundle")
    client = TestClient(create_policy_control_plane_app(
        settings=Settings(opa_control_plane_token="control-token", opa_bundle_path=bundle),
        repository=Repository(),
    ))

    assert client.get("/bundles/teoria.tar.gz").status_code == 401
    assert client.post("/logs", json=[]).status_code == 401
