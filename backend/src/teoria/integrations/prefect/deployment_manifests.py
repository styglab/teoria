"""Combine feature-owned Flow defaults with environment-owned execution bindings."""

from copy import deepcopy
from pathlib import Path

import yaml

DEPLOYMENT_FILES = {
    "ingestion": "specification_processing.yaml",  # Existing CLI kind is preserved.
    "legal-information": "legal_information.yaml",
    "model-operations": "model_operations.yaml",
    "metadata": "metadata_management.yaml",
}
DEPLOYMENT_ENVIRONMENTS = {"process": "compose", "kubernetes": "k3s"}


def deployment_directory(pipeline_root: Path, backend: str = "process") -> Path:
    try:
        environment = DEPLOYMENT_ENVIRONMENTS[backend]
    except KeyError:
        raise ValueError(f"Unsupported deployment backend: {backend}") from None
    return pipeline_root.resolve().parent / "deploy" / environment / "prefect"


def deployment_path(pipeline_root: Path, kind: str, backend: str = "process") -> Path:
    return deployment_directory(pipeline_root, backend) / DEPLOYMENT_FILES[kind]


def load_execution_policy(pipeline_root: Path, kind: str, backend: str) -> dict:
    path = deployment_path(pipeline_root, kind, backend)
    if not path.is_file():
        raise ValueError(f"Deployment kind {kind!r} is not supported by {backend!r}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_deployment_manifest(
    pipeline_root: Path, kind: str, backend: str = "process"
) -> dict:
    policy = load_execution_policy(pipeline_root, kind, backend)
    feature = Path(DEPLOYMENT_FILES[kind]).stem
    common = pipeline_root / "config" / feature / "prefect_deployments.yaml"
    document = deepcopy(yaml.safe_load(common.read_text(encoding="utf-8")))
    declarations = {item["name"]: item for item in document["deployments"]}
    bindings = {item["name"]: item for item in policy["deployments"]}
    if len(declarations) != len(document["deployments"]) or len(bindings) != len(
        policy["deployments"]
    ):
        raise ValueError("Duplicate deployment name")
    if declarations.keys() != bindings.keys():
        raise ValueError(
            f"Deployment bindings differ from shared declarations: {common}"
        )
    pools = {pool["name"]: pool for pool in policy["pools"]}
    for name, declaration in declarations.items():
        binding = bindings[name]
        if set(binding) - {"name", "work_pool", "parameters"}:
            raise ValueError(
                "Environment bindings may only set work_pool and environment parameters"
            )
        if set(declaration.get("parameters", {})) & set(binding.get("parameters", {})):
            raise ValueError(
                "Shared Flow parameters must not be duplicated in environment bindings"
            )
        pool = pools[binding["work_pool"]["name"]]
        queues = {queue["name"] for queue in pool.get("queues", [])} or {"default"}
        if binding["work_pool"]["work_queue_name"] not in queues:
            raise ValueError(f"Unconfigured work queue for deployment {name}")
        declaration["work_pool"] = deepcopy(binding["work_pool"])
        declaration.setdefault("parameters", {}).update(binding.get("parameters", {}))
    return document
