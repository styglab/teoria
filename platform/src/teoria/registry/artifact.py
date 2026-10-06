from __future__ import annotations

import json
import os
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from teoria.registry.loader import RegistryCatalog, RegistryLoader
from teoria.registry.release import CALVER_PATTERN, RegistryRelease, calculate_registry_checksum


class ActiveRegistryArtifact(BaseModel):
    version: str
    checksum: str


class RegistryArtifactError(RuntimeError):
    """Raised when a Runtime artifact is missing, mutable, or inconsistent."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def _checksum(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


class RuntimeBundleManifest(BaseModel):
    schema_version: str = "1.0"
    version: str
    created_at: datetime
    registry_version: str
    registry_checksum: str
    ontology_checksum: str
    ontology_artifact_count: int
    binding_checksum: str
    binding_count: int
    bundle_checksum: str

    def provenance(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class LoadedRuntimeBundle(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    manifest: RuntimeBundleManifest
    catalog: RegistryCatalog
    ontologies: list[dict[str, Any]]
    bindings: list[dict[str, Any]]


class RuntimeBundleCompiler:
    """Freeze Registry, published Ontology artifacts, and approved Bindings together."""

    def compile(
        self,
        registry_artifact: Path | str,
        *,
        ontologies: list[dict[str, Any]],
        bindings: list[dict[str, Any]],
        output: Path | str,
        version: str | None = None,
        created_at: datetime | None = None,
    ) -> RuntimeBundleManifest:
        source = Path(registry_artifact)
        catalog = RegistryArtifactLoader(source).load()
        assert catalog.release is not None
        bundle_version = version or catalog.release.version
        if not CALVER_PATTERN.fullmatch(bundle_version):
            raise ValueError("Runtime bundle version must use YYYY.MM.DD.REVISION format")
        for item in bindings:
            if item.get("status") != "approved":
                raise RegistryArtifactError("Runtime bundle can contain only approved bindings")
        normalized_ontologies = sorted(
            ontologies, key=lambda item: (str(item.get("namespace")), str(item.get("version")))
        )
        normalized_bindings = sorted(
            bindings, key=lambda item: (
                str(item.get("ontology_stable_key")),
                str(item.get("target_type")),
                str(item.get("target_locator")),
            ),
        )
        for item in normalized_ontologies:
            content = item.get("content")
            expected = str(item.get("checksum") or "")
            actual = hashlib.sha256(_canonical(content)).hexdigest()
            if expected.removeprefix("sha256:") != actual:
                raise RegistryArtifactError(
                    f"published Ontology artifact checksum mismatch: {item.get('namespace')}"
                )
        components = {
            "registry": catalog.release.checksum,
            "ontologies": _checksum(normalized_ontologies),
            "bindings": _checksum(normalized_bindings),
        }
        bundle_checksum = _checksum(components)
        destination = Path(output) / bundle_version
        if destination.exists():
            raise FileExistsError(f"Runtime bundle already exists: {destination}")
        shutil.copytree(source, destination)
        (destination / "ontologies.json").write_bytes(_canonical(normalized_ontologies) + b"\n")
        (destination / "bindings.json").write_bytes(_canonical(normalized_bindings) + b"\n")
        manifest = RuntimeBundleManifest(
            version=bundle_version,
            created_at=created_at or datetime.now(timezone.utc),
            registry_version=catalog.release.version,
            registry_checksum=catalog.release.checksum,
            ontology_checksum=components["ontologies"],
            ontology_artifact_count=len(normalized_ontologies),
            binding_checksum=components["bindings"],
            binding_count=len(normalized_bindings),
            bundle_checksum=bundle_checksum,
        )
        (destination / "bundle.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest


class RuntimeBundleLoader:
    def __init__(self, artifact: Path | str) -> None:
        self.artifact = Path(artifact)

    def load(self) -> LoadedRuntimeBundle:
        bundle_path = self.artifact / "bundle.json"
        if not bundle_path.is_file():
            raise RegistryArtifactError(f"Runtime bundle manifest is missing: {bundle_path}")
        try:
            manifest = RuntimeBundleManifest.model_validate_json(
                bundle_path.read_text(encoding="utf-8")
            )
            ontologies = json.loads((self.artifact / "ontologies.json").read_text(encoding="utf-8"))
            bindings = json.loads((self.artifact / "bindings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RegistryArtifactError(f"invalid Runtime bundle: {self.artifact}") from exc
        catalog = RegistryArtifactLoader(self.artifact).load()
        assert catalog.release is not None
        components = {
            "registry": catalog.release.checksum,
            "ontologies": _checksum(ontologies),
            "bindings": _checksum(bindings),
        }
        if manifest.version != self.artifact.name:
            raise RegistryArtifactError("Runtime bundle directory must match bundle version")
        if (
            manifest.registry_version != catalog.release.version
            or manifest.registry_checksum != components["registry"]
            or manifest.ontology_checksum != components["ontologies"]
            or manifest.binding_checksum != components["bindings"]
            or manifest.bundle_checksum != _checksum(components)
            or manifest.ontology_artifact_count != len(ontologies)
            or manifest.binding_count != len(bindings)
        ):
            raise RegistryArtifactError("Runtime bundle checksum or component manifest mismatch")
        return LoadedRuntimeBundle(
            manifest=manifest, catalog=catalog, ontologies=ontologies, bindings=bindings,
        )


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

    def load_active(self) -> LoadedRuntimeBundle:
        active = self._read_active()
        artifact = self.root / active.version
        bundle = RuntimeBundleLoader(artifact).load()
        if bundle.manifest.bundle_checksum != active.checksum:
            raise RegistryArtifactError("active Runtime bundle checksum mismatch")
        return bundle

    def activate(self, version: str) -> ActiveRegistryArtifact:
        artifact = self.root / version
        bundle = RuntimeBundleLoader(artifact).load()
        active = ActiveRegistryArtifact(
            version=bundle.manifest.version,
            checksum=bundle.manifest.bundle_checksum,
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
