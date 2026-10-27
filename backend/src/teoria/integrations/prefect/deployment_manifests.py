"""Locate version-controlled deployment declarations separately from feature code."""

from pathlib import Path


DEPLOYMENT_FILES = {
    "ingestion": "specification_processing.yaml",  # Existing CLI kind is preserved.
    "legal-information": "legal_information.yaml",
    "model-operations": "model_operations.yaml",
    "metadata": "metadata_management.yaml",
}


def deployment_directory(pipeline_root: Path) -> Path:
    """The backend and deploy directories are siblings in source and worker images."""
    return pipeline_root.resolve().parent / "deploy" / "prefect"


def deployment_path(pipeline_root: Path, kind: str) -> Path:
    return deployment_directory(pipeline_root) / DEPLOYMENT_FILES[kind]
