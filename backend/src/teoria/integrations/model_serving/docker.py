"""Restart one fixed demo server after an atomic, versioned model-release change."""

from __future__ import annotations

from contextlib import closing

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

import httpx


def _publish(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        json.dump(value, file)
        temporary = file.name
    os.chmod(
        temporary, 0o644
    )  # Release references contain no credentials; inference reads as a different UID.
    os.replace(temporary, path)


def activate_demo_release(release: dict) -> dict:
    import docker

    root = Path(os.environ["TEORIA_DEMO_RELEASE_DIRECTORY"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / "active.json"
    # The deployment worker has one flow slot; the filesystem lock also serializes CLI callers.
    with (root / "deployment.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = json.loads(path.read_text()) if path.exists() else None
        with closing(docker.from_env()) as client:
            container = client.containers.get("teoria-demo-inference-1")
            if container.labels.get("io.teoria.role") != "demo-inference":
                raise ValueError("refusing to restart an unexpected container")
            try:
                _publish(path, release)
                container.restart(timeout=20)
                with httpx.Client(timeout=5) as http:
                    for _ in range(60):
                        try:
                            response = http.get("http://demo-inference:8003/health")
                            if (
                                response.is_success
                                and response.json().get("model_version")
                                == release["model_version"]
                            ):
                                prediction = http.post(
                                    "http://demo-inference:8003/predict",
                                    headers={
                                        "Authorization": "Bearer "
                                        + os.environ["TEORIA_DEMO_INFERENCE_TOKEN"]
                                    },
                                    json={
                                        "tenure_months": 12,
                                        "monthly_spend": 50,
                                        "login_days_30d": 8,
                                        "support_tickets_30d": 3,
                                    },
                                )
                                prediction.raise_for_status()
                                return {
                                    **release,
                                    "status": "deployed",
                                    "smoke_prediction": prediction.json(),
                                }
                        except httpx.HTTPError:
                            pass
                        time.sleep(2)
                raise RuntimeError("demo inference readiness or prediction failed")
            except BaseException:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _publish(path, previous)
                container.restart(timeout=20)
                raise
