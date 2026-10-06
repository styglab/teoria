from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class RuntimeBundleFormatError(ValueError):
    """Raised when a bundle does not satisfy its declared format contract."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def checksum(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


@dataclass(frozen=True)
class RuntimeBundleComponents:
    ontologies: list[dict[str, Any]]
    bindings: list[dict[str, Any]]
    capabilities: list[dict[str, Any]]
    compatibility: list[dict[str, Any]]


class RuntimeBundleFormat(Protocol):
    schema_version: str

    def read(self, artifact: Path) -> RuntimeBundleComponents: ...

    def write(self, artifact: Path, components: RuntimeBundleComponents) -> None: ...

    def checksums(
        self, registry_checksum: str, components: RuntimeBundleComponents,
    ) -> dict[str, str]: ...

    def validate_manifest(
        self,
        manifest: Any,
        components: RuntimeBundleComponents,
        component_checksums: dict[str, str],
    ) -> None: ...


def _read_json(artifact: Path, filename: str) -> list[dict[str, Any]]:
    value = json.loads((artifact / filename).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeBundleFormatError(f"{filename} must contain a JSON array")
    return value


def _write_json(artifact: Path, filename: str, value: Any) -> None:
    (artifact / filename).write_bytes(canonical_json(value) + b"\n")


class RuntimeBundleFormatV1:
    schema_version = "1.0"

    def read(self, artifact: Path) -> RuntimeBundleComponents:
        return RuntimeBundleComponents(
            ontologies=_read_json(artifact, "ontologies.json"),
            bindings=_read_json(artifact, "bindings.json"),
            capabilities=[],
            compatibility=[],
        )

    def write(self, artifact: Path, components: RuntimeBundleComponents) -> None:
        _write_json(artifact, "ontologies.json", components.ontologies)
        _write_json(artifact, "bindings.json", components.bindings)

    def checksums(
        self, registry_checksum: str, components: RuntimeBundleComponents,
    ) -> dict[str, str]:
        return {
            "registry": registry_checksum,
            "ontologies": checksum(components.ontologies),
            "bindings": checksum(components.bindings),
        }

    def validate_manifest(
        self,
        manifest: Any,
        components: RuntimeBundleComponents,
        component_checksums: dict[str, str],
    ) -> None:
        return None


class RuntimeBundleFormatV2(RuntimeBundleFormatV1):
    schema_version = "2.0"

    def read(self, artifact: Path) -> RuntimeBundleComponents:
        return RuntimeBundleComponents(
            ontologies=_read_json(artifact, "ontologies.json"),
            bindings=_read_json(artifact, "bindings.json"),
            capabilities=_read_json(artifact, "capabilities.json"),
            compatibility=_read_json(artifact, "compatibility.json"),
        )

    def write(self, artifact: Path, components: RuntimeBundleComponents) -> None:
        super().write(artifact, components)
        _write_json(artifact, "capabilities.json", components.capabilities)
        _write_json(artifact, "compatibility.json", components.compatibility)

    def checksums(
        self, registry_checksum: str, components: RuntimeBundleComponents,
    ) -> dict[str, str]:
        result = super().checksums(registry_checksum, components)
        result.update({
            "capabilities": checksum(components.capabilities),
            "compatibility": checksum(components.compatibility),
        })
        return result

    def validate_manifest(
        self,
        manifest: Any,
        components: RuntimeBundleComponents,
        component_checksums: dict[str, str],
    ) -> None:
        if (
            manifest.capability_checksum != component_checksums["capabilities"]
            or manifest.compatibility_checksum != component_checksums["compatibility"]
            or manifest.capability_count != len(components.capabilities)
        ):
            raise RuntimeBundleFormatError("Runtime bundle Capability manifest mismatch")


_FORMATS: dict[str, RuntimeBundleFormat] = {
    format_.schema_version: format_
    for format_ in (RuntimeBundleFormatV1(), RuntimeBundleFormatV2())
}


def get_runtime_bundle_format(schema_version: str) -> RuntimeBundleFormat:
    try:
        return _FORMATS[schema_version]
    except KeyError as exc:
        raise RuntimeBundleFormatError(
            f"unsupported Runtime bundle schema: {schema_version}"
        ) from exc
