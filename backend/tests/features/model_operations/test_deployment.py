import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from teoria.integrations.model_serving.docker import activate_demo_release


def configure(monkeypatch, tmp_path, *, healthy):
    restarts = []
    closed = []
    container = SimpleNamespace(
        labels={"io.teoria.role": "demo-inference"},
        restart=lambda **kw: restarts.append(kw),
    )
    client = SimpleNamespace(
        containers=SimpleNamespace(get=lambda name: container),
        close=lambda: closed.append(True),
    )
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))
    monkeypatch.setenv("TEORIA_DEMO_RELEASE_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("TEORIA_DEMO_INFERENCE_TOKEN", "synthetic-test-token")
    monkeypatch.setattr(
        "teoria.integrations.model_serving.docker.time.sleep", lambda seconds: None
    )

    class Http:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            return (
                httpx.Response(200, json={"model_version": 2})
                if healthy
                else httpx.Response(503)
            )

        def post(self, url, **kwargs):
            return httpx.Response(
                200, json={"model_version": 2}, request=httpx.Request("POST", url)
            )

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: Http())
    return restarts, closed


def test_deployment_checks_readiness_and_publishes_a_readable_release(
    monkeypatch, tmp_path
):
    restarts, closed = configure(monkeypatch, tmp_path, healthy=True)
    release = {"model_version": 2, "sha256": "demo"}
    assert activate_demo_release(release)["status"] == "deployed"
    assert json.loads((tmp_path / "active.json").read_text()) == release
    assert (tmp_path / "active.json").stat().st_mode & 0o777 == 0o644
    assert len(restarts) == 1 and closed == [True]


def test_failed_readiness_restores_previous_release(monkeypatch, tmp_path):
    restarts, closed = configure(monkeypatch, tmp_path, healthy=False)
    previous = {"model_version": 1, "sha256": "previous"}
    (tmp_path / "active.json").write_text(json.dumps(previous))
    with pytest.raises(RuntimeError):
        activate_demo_release({"model_version": 2, "sha256": "candidate"})
    assert json.loads((tmp_path / "active.json").read_text()) == previous
    assert len(restarts) == 2 and closed == [True]
