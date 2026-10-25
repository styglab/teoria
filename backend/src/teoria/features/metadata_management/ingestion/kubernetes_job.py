"""Run the pinned OpenMetadata ingestion image as a namespaced Kubernetes Job."""

from __future__ import annotations

import os
import time
from uuid import uuid4


def run_ingestion_job(*, image: str, timeout_seconds: int) -> dict:
    from kubernetes import client, config

    config.load_incluster_config()
    namespace = os.environ.get("TEORIA_KUBERNETES_NAMESPACE", "teoria")
    pull_secret = os.environ.get(
        "TEORIA_KUBERNETES_IMAGE_PULL_SECRET", "teoria-registry"
    )
    name = "openmetadata-ingestion-" + uuid4().hex[:12]
    api = client.BatchV1Api()
    body = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": {"app": "openmetadata-ingestion"}},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": timeout_seconds,
            "ttlSecondsAfterFinished": 300,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "imagePullSecrets": [{"name": pull_secret}],
                    "containers": [
                        {
                            "name": "ingestion",
                            "image": image,
                            "command": [
                                "metadata",
                                "ingest",
                                "-c",
                                "/config/teoria-postgres.yaml",
                            ],
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "512Mi"},
                                "limits": {"cpu": "1", "memory": "2Gi"},
                            },
                            "env": [
                                {
                                    "name": key,
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "teoria-secrets",
                                            "key": key,
                                        }
                                    },
                                }
                                for key in [
                                    "TEORIA_METADATA_DB_PASSWORD",
                                    "OPENMETADATA_INGESTION_BOT_TOKEN",
                                ]
                            ],
                        }
                    ],
                }
            },
        },
    }
    created = False
    try:
        api.create_namespaced_job(namespace, body)
        created = True
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = api.read_namespaced_job_status(name, namespace).status
            if status.succeeded:
                return {"status": "completed", "status_code": 0, "image": image}
            if status.failed:
                raise RuntimeError("OpenMetadata ingestion Kubernetes Job failed")
            time.sleep(5)
        raise TimeoutError("OpenMetadata ingestion Kubernetes Job timed out")
    finally:
        if created:
            api.delete_namespaced_job(name, namespace, propagation_policy="Background")
