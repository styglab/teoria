"""Register shared Prefect deployments and bounded execution policies."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import yaml


def kubernetes_job_template() -> dict:
    from prefect_kubernetes.worker import KubernetesWorker

    template = KubernetesWorker.get_default_base_job_template()
    properties = template["variables"]["properties"]
    defaults = {
        "namespace": "teoria-pipelines",
        "image": os.environ["TEORIA_PIPELINE_JOB_IMAGE"],
        "cpu_request": os.getenv("TEORIA_JOB_CPU_REQUEST", "1"),
        "cpu_limit": os.getenv("TEORIA_JOB_CPU_LIMIT", "2"),
        "memory_request": os.getenv("TEORIA_JOB_MEMORY_REQUEST", "2Gi"),
        "memory_limit": os.getenv("TEORIA_JOB_MEMORY_LIMIT", "4Gi"),
        "finished_job_ttl": 3600,
        "pod_watch_timeout_seconds": 600,
    }
    for key, value in defaults.items():
        properties[key]["default"] = value
    job = template["job_configuration"]["job_manifest"]["spec"]
    pod = job["template"]["spec"]
    # These are Job fields; keep the SDK's defaults out of the PodSpec.
    for key in ("completions", "parallelism"):
        pod.pop(key, None)
        job[key] = 1
    pod["automountServiceAccountToken"] = False
    pod["imagePullSecrets"] = [{"name": "teoria-registry"}]
    pod["containers"][0]["envFrom"] = [
        {"secretRef": {"name": "teoria-pipeline-secrets"}}
    ]
    template["job_configuration"]["env"] = {
        "TEORIA_ENVIRONMENT": "production",
        "TEORIA_PIPELINE_PATH": "/app/pipelines",
        "PREFECT_API_URL": "http://prefect-server.teoria.svc.cluster.local:4200/api",
        # Do not persist the dispatcher's auth value into the job manifest.
        # The run receives it from the namespace's restricted Secret instead.
        "PREFECT_API_AUTH_STRING": None,
    }
    return template


def positive_setting(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


async def configure_pool(client, *, backend: str, kind: str) -> str:
    from prefect.client.schemas.actions import WorkPoolCreate, WorkPoolUpdate
    from prefect.exceptions import ObjectNotFound
    from prefect.workers.process import ProcessWorker

    if kind == "metadata":
        pool_name, pool_type, concurrency = "teoria-metadata", "process", 1
        template = ProcessWorker.get_default_base_job_template()
        queues = [("default", 1, 1)]
    elif kind == "legal-information":
        pool_name = ("teoria-legal-information-k3s" if backend == "kubernetes"
                     else "teoria-legal-information")
        pool_type, concurrency = backend, 1
        template = (kubernetes_job_template() if backend == "kubernetes"
                    else ProcessWorker.get_default_base_job_template())
        if backend == "kubernetes":
            pod = template["job_configuration"]["job_manifest"]["spec"]["template"]["spec"]
            pod["containers"][0]["envFrom"] = [
                {"secretRef": {"name": "teoria-legal-information-secrets"}}
            ]
        queues = [("laws", 1, 1)]
    else:
        concurrency = positive_setting("TEORIA_PIPELINE_CONCURRENCY", 2)
        pool_type = backend
        pool_name = (
            "teoria-specification-k3s" if backend == "kubernetes" else "teoria-specification"
        )
        template = (
            kubernetes_job_template()
            if backend == "kubernetes"
            else ProcessWorker.get_default_base_job_template()
        )
        queues = [("documents", 1, concurrency)]
    try:
        existing = await client.read_work_pool(pool_name)
    except ObjectNotFound:
        existing = None
    if existing is not None and existing.type != pool_type:
        raise ValueError(f"Work pool {pool_name} has incompatible type {existing.type}")
    if existing is None:
        await client.create_work_pool(
            WorkPoolCreate(
                name=pool_name,
                type=pool_type,
                base_job_template=template,
                concurrency_limit=concurrency,
            )
        )
    else:
        await client.update_work_pool(
            pool_name,
            WorkPoolUpdate(
                base_job_template=template,
                concurrency_limit=concurrency,
            ),
        )
    for name, priority, limit in queues:
        try:
            queue = await client.read_work_queue_by_name(name, work_pool_name=pool_name)
        except ObjectNotFound:
            await client.create_work_queue(
                name,
                work_pool_name=pool_name,
                priority=priority,
                concurrency_limit=limit,
            )
        else:
            await client.update_work_queue(
                queue.id, priority=priority, concurrency_limit=limit
            )
    return pool_name


def register_deployments(
    pipeline_root: Path,
    *,
    backend: str,
    kind: str,
) -> None:
    from prefect.client.orchestration import get_client

    if backend not in {"process", "kubernetes"} or kind not in {
        "ingestion",
        "metadata",
        "legal-information",
        "all",
    }:
        raise ValueError("Unsupported deployment backend or kind")
    kinds = ("ingestion", "legal-information", "metadata") if kind == "all" else (kind,)

    async def configure() -> dict[str, str]:
        async with get_client() as client:
            return {
                item: await configure_pool(client, backend=backend, kind=item)
                for item in kinds
            }

    pools = asyncio.run(configure())
    with tempfile.TemporaryDirectory(prefix="teoria_prefect_") as directory:
        for item in kinds:
            filename = (
                "prefect.yaml" if item == "ingestion" else
                "prefect.legal_information.yaml" if item == "legal-information" else
                "prefect.metadata.yaml"
            )
            document = yaml.safe_load((pipeline_root / filename).read_text())
            for deployment in document["deployments"]:
                deployment["work_pool"]["name"] = pools[item]
                if item in {"ingestion", "legal-information"}:
                    queue = deployment["work_pool"]["work_queue_name"]
                    if queue != ("laws" if item == "legal-information" else "documents"):
                        raise ValueError(f"Unconfigured ingestion queue: {queue}")
                elif image := os.getenv("TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE"):
                    deployment["parameters"]["image"] = image
            target = Path(directory) / filename
            target.write_text(yaml.safe_dump(document, allow_unicode=True))
            subprocess.run(
                ["prefect", "deploy", "--all", "--prefect-file", str(target)],
                check=True,
            )
