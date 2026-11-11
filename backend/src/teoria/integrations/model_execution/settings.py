"""Operator-owned execution policy; workload requests cannot override these privileges."""
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionSettings:
    backend: str
    project: str
    network: str
    namespace: str
    mlflow_url: str
    allowed_registries: tuple[str, ...]
    workload_environment: dict[str, str]
    kubernetes_url: str
    kubernetes_token_file: str
    kubernetes_ca_file: str
    image_pull_secret: str
    workload_secret: str

    @classmethod
    def from_environment(cls):
        project = os.getenv("TEORIA_COMPOSE_PROJECT_NAME", "teoria")
        return cls(
            backend=os.getenv("TEORIA_MODEL_EXECUTION_BACKEND", "docker"),
            project=project, network=os.getenv("TEORIA_MODEL_DOCKER_NETWORK", project + "_default"),
            namespace=os.getenv("TEORIA_MODEL_KUBERNETES_NAMESPACE", "teoria-models"),
            mlflow_url=os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000/mlflow"),
            allowed_registries=tuple(filter(None, os.getenv("TEORIA_MODEL_ALLOWED_REGISTRIES", "").split(","))),
            workload_environment=json.loads(os.getenv("TEORIA_MODEL_WORKLOAD_ENVIRONMENT", "") or "{}"),
            kubernetes_url=os.getenv("TEORIA_MODEL_KUBERNETES_URL", "https://kubernetes.default.svc"),
            kubernetes_token_file=os.getenv("TEORIA_MODEL_KUBERNETES_TOKEN_FILE", "/var/run/secrets/kubernetes.io/serviceaccount/token"),
            kubernetes_ca_file=os.getenv("TEORIA_MODEL_KUBERNETES_CA_FILE", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"),
            image_pull_secret=os.getenv("TEORIA_MODEL_IMAGE_PULL_SECRET", "model-images"),
            workload_secret=os.getenv("TEORIA_MODEL_WORKLOAD_SECRET", "model-workload"),
        )

    def validate_image(self, image):
        if not self.allowed_registries or image.split("/", 1)[0] not in self.allowed_registries:
            raise ValueError("model image registry is not allowed by the operator")
