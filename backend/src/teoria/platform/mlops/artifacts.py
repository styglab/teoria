"""Bounded workload logs and verified MLflow result references."""
import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field

from teoria.integrations.s3 import S3Client
from teoria.platform.mlops.contracts import ModelName


class TrainingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model_name: ModelName
    model_version: int = Field(ge=1)
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(min_length=1, max_length=200)


def storage(client):
    workload = json.loads(os.getenv("TEORIA_MODEL_WORKLOAD_ENVIRONMENT", "{}") or "{}")
    return S3Client(client,
        endpoint=os.getenv("TEORIA_MODEL_STORAGE_ENDPOINT", workload.get("AWS_ENDPOINT_URL_S3", "http://minio:9000")),
        access_key=os.getenv("TEORIA_MODEL_STORAGE_ACCESS_KEY") or workload.get("AWS_ACCESS_KEY_ID"),
        secret_key=os.getenv("TEORIA_MODEL_STORAGE_SECRET_KEY") or workload.get("AWS_SECRET_ACCESS_KEY"))


def redact_log(data, extra_secrets=()):
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    workload = json.loads(os.getenv("TEORIA_MODEL_WORKLOAD_ENVIRONMENT", "{}") or "{}")
    secrets = [*extra_secrets, *(v for k,v in os.environ.items() if re.search(r"PASSWORD|TOKEN|SECRET|DATABASE_URL|AUTH_STRING", k)),
               *(v for k,v in workload.items() if re.search(r"PASSWORD|TOKEN|SECRET", k))]
    for value in sorted((str(v) for v in secrets if v and len(str(v)) >= 4), key=len, reverse=True):
        text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(Bearer|Basic)\s+[A-Za-z0-9+/=._-]+", r"\1 [redacted]", text)
    return re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)


async def preserve_logs(client, run_id, data):
    uri = os.getenv("TEORIA_MODEL_ARTIFACT_ROOT", "s3://teoria-mlops") + "/logs/" + run_id + ".txt"
    await storage(client).put(uri, redact_log(data).encode()[-4*1024*1024:], "text/plain; charset=utf-8")
    return uri


async def verify_result(client, spec, run_id, mlflow_url):
    body = await storage(client).get(spec.output_uri)
    result = TrainingResult.model_validate_json(body)
    if result.model_name != spec.model_name:
        raise ValueError("training result model name mismatch")
    base = mlflow_url.rstrip("/")
    response = await client.get(base + "/api/2.0/mlflow/model-versions/get",
                               params={"name": result.model_name, "version": result.model_version})
    response.raise_for_status()
    version = response.json()["model_version"]
    if version.get("run_id") != result.run_id:
        raise ValueError("MLflow model version does not match training result")
    response = await client.get(base + "/api/2.0/mlflow/runs/get", params={"run_id": result.run_id})
    response.raise_for_status()
    tags = {t["key"]:t["value"] for t in response.json()["run"].get("data", {}).get("tags", [])}
    if tags.get("teoria.prefect_flow_run_id", tags.get("teoria.training_run_id")) != run_id:
        raise ValueError("MLflow run is not linked to this training execution")
    for key,value in {"teoria.prefect_flow_run_id": run_id, "teoria.training_image": spec.image,
                      "teoria.input_uri": spec.input_uri, "teoria.input_sha256": spec.input_sha256,
                      **({"teoria.configuration_id":spec.configuration_id,"teoria.configuration_revision":str(spec.configuration_revision)} if spec.configuration_id else {})}.items():
        response = await client.post(base + "/api/2.0/mlflow/runs/set-tag", json={"run_id": result.run_id,"key":key,"value":value})
        response.raise_for_status()
    version_tags = {tag["key"]:tag["value"] for tag in version.get("tags", [])}
    if version_tags.get("teoria.model_sha256") != result.model_sha256:
        raise ValueError("MLflow model checksum reference mismatch")
    return result.model_dump()
