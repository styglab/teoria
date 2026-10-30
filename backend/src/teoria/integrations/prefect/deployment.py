"""Register feature-owned Flows using environment-specific execution policies."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from teoria.integrations.prefect.deployment_manifests import (
    deployment_directory,
    load_deployment_manifest,
    load_execution_policy,
)


def pipeline_directory(pipeline_root: Path | None = None) -> Path:
    return pipeline_root or Path(os.getenv("TEORIA_PIPELINE_PATH", "backend"))


def kubernetes_job_template(
    pipeline_root: Path | None = None, *, secret_name: str | None = None
) -> dict:
    from prefect_kubernetes.worker import KubernetesWorker

    path = (
        deployment_directory(pipeline_directory(pipeline_root), "kubernetes")
        / "execution.yaml"
    )
    policy = yaml.safe_load(path.read_text())
    template = KubernetesWorker.get_default_base_job_template()
    properties = template["variables"]["properties"]
    defaults = dict(policy["defaults"])
    defaults.update(
        namespace=policy["namespace"], image=os.environ[policy["image_env"]]
    )
    for key, variable in policy.get("overrides", {}).items():
        defaults[key] = os.getenv(variable, defaults[key])
    for key, value in defaults.items():
        properties[key]["default"] = value
    job = template["job_configuration"]["job_manifest"]["spec"]
    pod = job["template"]["spec"]
    # These are Job fields; keep the SDK's defaults out of the PodSpec.
    for key in ("completions", "parallelism"):
        pod.pop(key, None)
        job[key] = 1
    pod["automountServiceAccountToken"] = False
    pod["imagePullSecrets"] = [{"name": policy["image_pull_secret"]}]
    pod["containers"][0]["envFrom"] = [
        {"secretRef": {"name": secret_name or policy["job_secret"]}}
    ]
    # Never materialize the dispatcher's credentials into the Job declaration.
    template["job_configuration"]["env"] = policy["environment"]
    return template


def positive_setting(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


async def configure_pool(
    client, *, backend: str, kind: str, pipeline_root: Path | None = None
) -> str:
    from prefect.client.schemas.actions import WorkPoolCreate, WorkPoolUpdate
    from prefect.exceptions import ObjectNotFound
    from prefect.workers.process import ProcessWorker

    root = pipeline_directory(pipeline_root)
    policy = load_execution_policy(root, kind, backend)
    for pool in policy["pools"]:
        concurrency = (
            positive_setting(pool["concurrency_limit_env"], pool["concurrency_limit"])
            if pool.get("concurrency_limit_env")
            else pool["concurrency_limit"]
        )
        template = (
            kubernetes_job_template(root, secret_name=pool["job_secret"])
            if pool["type"] == "kubernetes"
            else ProcessWorker.get_default_base_job_template()
        )
        pool_name = pool["name"]
        try:
            existing = await client.read_work_pool(pool_name)
        except ObjectNotFound:
            existing = None
        if existing is not None and existing.type != pool["type"]:
            raise ValueError(
                f"Work pool {pool_name} has incompatible type {existing.type}"
            )
        if existing is None:
            await client.create_work_pool(
                WorkPoolCreate(
                    name=pool_name,
                    type=pool["type"],
                    base_job_template=template,
                    concurrency_limit=concurrency,
                )
            )
        elif pool.get("update_existing", True):
            await client.update_work_pool(
                pool_name,
                WorkPoolUpdate(
                    base_job_template=template, concurrency_limit=concurrency
                ),
            )
        for queue in pool.get("queues", []):
            limit = (
                positive_setting(
                    queue["concurrency_limit_env"], queue["concurrency_limit"]
                )
                if queue.get("concurrency_limit_env")
                else queue["concurrency_limit"]
            )
            try:
                existing_queue = await client.read_work_queue_by_name(
                    queue["name"], work_pool_name=pool_name
                )
            except ObjectNotFound:
                await client.create_work_queue(
                    queue["name"],
                    work_pool_name=pool_name,
                    priority=queue["priority"],
                    concurrency_limit=limit,
                )
            else:
                await client.update_work_queue(
                    existing_queue.id,
                    priority=queue["priority"],
                    concurrency_limit=limit,
                )
    return policy["pools"][0]["name"]


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
        "model-operations",
        "all",
    }:
        raise ValueError("Unsupported deployment backend or kind")
    kinds = ("ingestion", "legal-information", "metadata") if kind == "all" else (kind,)
    documents = {
        item: load_deployment_manifest(pipeline_root, item, backend) for item in kinds
    }

    async def configure() -> dict[str, str]:
        async with get_client() as client:
            return {
                item: await configure_pool(
                    client, backend=backend, kind=item, pipeline_root=pipeline_root
                )
                for item in kinds
            }

    pools = asyncio.run(configure())
    with tempfile.TemporaryDirectory(prefix="teoria_prefect_") as directory:
        for item in kinds:
            document = documents[item]
            filename = f"{item}.yaml"
            for deployment in document["deployments"]:
                if (
                    item != "model-operations"
                    and deployment["work_pool"]["name"] != pools[item]
                ):
                    raise ValueError(
                        "Deployment pool differs from configured environment pool"
                    )
                if item in {"ingestion", "legal-information"}:
                    queue = deployment["work_pool"]["work_queue_name"]
                    if queue != (
                        "laws" if item == "legal-information" else "documents"
                    ):
                        raise ValueError(f"Unconfigured ingestion queue: {queue}")
                elif item == "metadata" and (
                    image := os.getenv("TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE")
                ):
                    deployment["parameters"]["image"] = image
            target = Path(directory) / filename
            target.write_text(yaml.safe_dump(document, allow_unicode=True))
            subprocess.run(
                ["prefect", "deploy", "--all", "--prefect-file", str(target)],
                check=True,
            )
