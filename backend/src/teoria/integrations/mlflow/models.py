from __future__ import annotations

import hashlib
import os
from pathlib import Path

MODEL_NAME = "teoria_demo_customer_churn"


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
    dataset_version: str,
    dataset_checksum: str,
    requested_by: str,
) -> dict:
    import mlflow
    import mlflow.sklearn
    from mlflow.models import infer_signature

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment("teoria_synthetic_customer_churn")
    with mlflow.start_run(
        tags={"teoria.synthetic": "true", "teoria.requested_by": requested_by}
    ) as run:
        mlflow.log_params(
            {
                "dataset_version": dataset_version,
                "dataset_sha256": dataset_checksum,
                "split_seed": 42,
                "personal_attributes_in_features": False,
            }
        )
        mlflow.log_metrics(metrics)
        info = mlflow.sklearn.log_model(
            model,
            name="customer_churn",
            signature=infer_signature(frame, model.predict(frame)),
            input_example=frame.head(2),
            registered_model_name=MODEL_NAME,
        )
        return {
            "run_id": run.info.run_id,
            "model_name": MODEL_NAME,
            "model_version": str(info.registered_model_version),
            "model_uri": info.model_uri,
            "metrics": metrics,
            "dataset_checksum": dataset_checksum,
            "synthetic": True,
        }


def download_version(version: int, destination: str) -> tuple[str, str]:
    import mlflow

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    path = mlflow.artifacts.download_artifacts(
        artifact_uri=f"models:/{MODEL_NAME}/{version}", dst_path=destination
    )
    return path, model_checksum(path)
