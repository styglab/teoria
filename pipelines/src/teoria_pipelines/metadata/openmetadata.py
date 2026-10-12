"""Prefect orchestration for isolated OpenMetadata ingestion containers."""

from __future__ import annotations

import os
from typing import Any

from prefect import flow, get_run_logger, task


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


@task(name="OpenMetadata metadata ingestion Job 실행", retries=2, retry_delay_seconds=60)
def run_openmetadata_ingestion_container(
    *,
    image: str,
    network: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run the official ingestion runtime as an ephemeral Docker container."""

    import docker

    logger = get_run_logger()
    allowed_image = _required_environment(
        "TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE"
    )
    if image != allowed_image:
        raise RuntimeError(
            "OpenMetadata ingestion image is not allowlisted: "
            f"requested={image!r}"
        )
    environment = {
        "TEORIA_METADATA_DB_PASSWORD": _required_environment(
            "TEORIA_METADATA_DB_PASSWORD"
        ),
        "OPENMETADATA_INGESTION_BOT_TOKEN": _required_environment(
            "OPENMETADATA_INGESTION_BOT_TOKEN"
        ),
    }
    client = docker.from_env()
    container = client.containers.run(
        image=image,
        name=None,
        command=["ingest", "-c", "/config/teoria-postgres.yaml"],
        entrypoint=["metadata"],
        environment=environment,
        network=network,
        detach=True,
        auto_remove=False,
        labels={
            "io.teoria.owner": "prefect",
            "io.teoria.job": "openmetadata-ingestion",
        },
    )
    try:
        result = container.wait(timeout=timeout_seconds)
        for line in container.logs(stream=True, follow=False):
            logger.info(line.decode("utf-8", errors="replace").rstrip())
        status_code = int(result.get("StatusCode", 1))
        if status_code != 0:
            raise RuntimeError(
                f"OpenMetadata ingestion container exited with status {status_code}"
            )
        return {"status": "completed", "status_code": status_code, "image": image}
    finally:
        container.remove(force=True)
        client.close()


@flow(name="OpenMetadata PostgreSQL 메타데이터 동기화", log_prints=False)
def sync_openmetadata_postgres(
    image: str = "teoria-openmetadata-ingestion:1.12.6",
    network: str = "teoria_default",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Synchronize Teoria Data PostgreSQL metadata into OpenMetadata."""

    return run_openmetadata_ingestion_container(
        image=image,
        network=network,
        timeout_seconds=timeout_seconds,
    )
