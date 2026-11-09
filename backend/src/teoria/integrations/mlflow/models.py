from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx


def model_checksum(directory: str) -> str:
    root = Path(directory)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def register_model(
    model,
    metrics: dict,
    frame,
    *,
    model_name: str,
    experiment_name: str,
    artifact_name: str,
    parameters: dict,
    tags: dict,
) -> dict:
    import mlflow
    import mlflow.sklearn
    from mlflow.models import infer_signature

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(tags=tags) as run:
        mlflow.log_params(parameters)
        mlflow.log_metrics(metrics)
        info = mlflow.sklearn.log_model(
            model,
            name=artifact_name,
            signature=infer_signature(frame, model.predict(frame)),
            input_example=frame.head(2),
            registered_model_name=model_name,
        )
        return {
            "run_id": run.info.run_id,
            "model_name": model_name,
            "model_version": str(info.registered_model_version),
            "model_uri": info.model_uri,
            "metrics": metrics,
        }


def download_version(
    model_name: str, version: int, destination: str
) -> tuple[str, str]:
    import mlflow

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    path = mlflow.artifacts.download_artifacts(
        artifact_uri=f"models:/{model_name}/{version}", dst_path=destination
    )
    return path, model_checksum(path)


async def search_registered_models(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    query: str = "",
    page_token: str | None = None,
) -> dict:
    escaped = query.replace("\\", "\\\\").replace("'", "\\'")
    response = await client.get(
        base_url.rstrip("/") + "/api/2.0/mlflow/registered-models/search",
        params={
            "max_results": 25,
            **({"filter": "name ILIKE '%" + escaped + "%'"} if query else {}),
            **({"page_token": page_token} if page_token else {}),
        },
    )
    response.raise_for_status()
    return response.json()


async def search_model_versions(
    client: httpx.AsyncClient,
    base_url: str,
    model_name: str,
    *,
    page_token: str | None = None,
) -> dict:
    escaped = model_name.replace("\\", "\\\\").replace("'", "\\'")
    response = await client.get(
        base_url.rstrip("/") + "/api/2.0/mlflow/model-versions/search",
        params={
            "filter": f"name = '{escaped}'",
            "max_results": 25,
            "order_by": "version_number DESC",
            **({"page_token": page_token} if page_token else {}),
        },
    )
    response.raise_for_status()
    return response.json()


async def read_model_run(client: httpx.AsyncClient, base_url: str, run_id: str) -> dict:
    response = await client.get(
        base_url.rstrip("/") + "/api/2.0/mlflow/runs/get", params={"run_id": run_id}
    )
    response.raise_for_status()
    return response.json()["run"]
