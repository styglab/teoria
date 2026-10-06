from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.release import RegistryRelease, calculate_registry_checksum


class ActiveRegistryArtifact(BaseModel):
    version: str
    checksum: str


class RegistryArtifactError(RuntimeError):
    """Raised when a Runtime artifact is missing, mutable, or inconsistent."""


class RegistryArtifactLoader:
    """Load only a checksum-valid, versioned Registry artifact."""

    def __init__(self, artifact: Path | str) -> None:
        self.artifact = Path(artifact)

    def load(self) -> RegistryCatalog:
        manifest_path = self.artifact / "manifest.json"
        registry_root = self.artifact / "registries"
        if not manifest_path.is_file() or not registry_root.is_dir():
            raise RegistryArtifactError(
                f"invalid Registry artifact layout: {self.artifact}"
            )
        try:
            manifest = RegistryRelease.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise RegistryArtifactError(
                f"invalid Registry artifact manifest: {manifest_path}"
            ) from exc
        if manifest.status != "published":
            raise RegistryArtifactError("Registry artifact must be published")
        if self.artifact.name != manifest.version:
            raise RegistryArtifactError(
                "Registry artifact directory must match manifest version"
            )
        actual_checksum = calculate_registry_checksum(registry_root)
        if actual_checksum != manifest.checksum:
            raise RegistryArtifactError(
                "Registry artifact checksum does not match its immutable manifest"
            )
        catalog = RegistryLoader(registry_root).load()
        if catalog.release is None or catalog.release.status != "published":
            raise RegistryArtifactError(
                "Registry artifact does not contain a checksum-valid release"
            )
        if catalog.release.public_dict() != manifest.public_dict():
            raise RegistryArtifactError(
                "Registry artifact manifest differs from its embedded release"
            )
        return catalog


class RegistryArtifactStore:
    """Resolve and atomically activate immutable Registry versions."""

    ACTIVE_FILE = "active.json"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def load_active(self) -> RegistryCatalog:
        active = self._read_active()
        artifact = self.root / active.version
        catalog = RegistryArtifactLoader(artifact).load()
        if catalog.release is None or catalog.release.checksum != active.checksum:
            raise RegistryArtifactError("active Registry artifact checksum mismatch")
        return catalog

    def activate(self, version: str) -> ActiveRegistryArtifact:
        artifact = self.root / version
        catalog = RegistryArtifactLoader(artifact).load()
        assert catalog.release is not None
        active = ActiveRegistryArtifact(
            version=catalog.release.version,
            checksum=catalog.release.checksum,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{self.ACTIVE_FILE}.{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps(active.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.root / self.ACTIVE_FILE)
        return active

    def _read_active(self) -> ActiveRegistryArtifact:
        path = self.root / self.ACTIVE_FILE
        if not path.is_file():
            raise RegistryArtifactError(f"active Registry artifact is not configured: {path}")
        try:
            return ActiveRegistryArtifact.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise RegistryArtifactError(f"invalid active Registry artifact: {path}") from exc
