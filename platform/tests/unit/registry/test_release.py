import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.release import calculate_registry_checksum, publish_registry
from teoria.registry.artifact import (
    RegistryArtifactError,
    RegistryArtifactLoader,
    RegistryArtifactStore,
    RuntimeBundleCompiler,
    RuntimeBundleLoader,
    _checksum,
)


def test_publish_keeps_authored_registry_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    registry = root / "example.yaml"
    registry.write_text("value: 1\n", encoding="utf-8")

    release = publish_registry(
        root,
        version="2026.08.05.1",
        output=tmp_path / "dist",
        git_commit="abc123",
        published_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    assert release.checksum == calculate_registry_checksum(root)
    assert not (root / ".release.json").exists()
    manifest = json.loads(
        (tmp_path / "dist" / "2026.08.05.1" / "manifest.json").read_text()
    )
    assert manifest["version"] == "2026.08.05.1"


def test_publish_excludes_legacy_source_release_file(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "example.yaml").write_text("value: 1\n", encoding="utf-8")
    (root / ".release.json").write_text('{"legacy": true}\n', encoding="utf-8")

    publish_registry(
        root, version="2026.08.05.1", output=tmp_path / "dist", git_commit="abc123"
    )

    assert not (
        tmp_path / "dist" / "2026.08.05.1" / "registries" / ".release.json"
    ).exists()


def test_publish_can_create_an_immutable_artifact(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "example.yaml").write_text("value: 1\n", encoding="utf-8")

    publish_registry(root, version="2026.08.05.1", output=tmp_path / "dist", git_commit="abc123")

    artifact = tmp_path / "dist" / "2026.08.05.1"
    assert (artifact / "manifest.json").is_file()
    assert (artifact / "registries" / "example.yaml").is_file()


def test_artifact_loader_rejects_modified_content(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "core").mkdir()
    (root / "core" / "data_types.yaml").write_text(
        "registry:\n  version: 1.0.0\n  registered_at: '2026-08-05'\n"
        "data_types:\n  - id: text\n    name: Text\n    base_type: string\n",
        encoding="utf-8",
    )
    publish_registry(root, version="2026.08.05.1", output=tmp_path / "dist", git_commit="abc123")
    artifact = tmp_path / "dist" / "2026.08.05.1"

    RegistryArtifactLoader(artifact).load()
    (artifact / "registries" / "core" / "data_types.yaml").write_text(
        "registry:\n  version: 1.0.0\n  registered_at: '2026-08-05'\n"
        "data_types: []\n", encoding="utf-8"
    )

    with pytest.raises(RegistryArtifactError, match="checksum"):
        RegistryArtifactLoader(artifact).load()


def test_artifact_store_atomically_activates_a_valid_version(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "core").mkdir()
    (root / "core" / "data_types.yaml").write_text(
        "registry:\n  version: 1.0.0\n  registered_at: '2026-08-05'\n"
        "data_types:\n  - id: text\n    name: Text\n    base_type: string\n",
        encoding="utf-8",
    )
    registry_root = tmp_path / "registry_dist"
    store_root = tmp_path / "bundle_dist"
    ontology_content = {"namespace": "example", "version": "1.0", "objects": []}
    ontology = {
        "namespace": "example",
        "version": "1.0",
        "content": ontology_content,
        "checksum": hashlib.sha256(json.dumps(
            ontology_content, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        ).encode()).hexdigest(),
    }
    binding = {
        "status": "approved",
        "ontology_stable_key": "example.Contract.amount",
        "target_type": "capability_output",
        "target_locator": "capability://search_contracts/current_contract_amount",
    }
    publish_registry(root, version="2026.08.05.1", output=registry_root, git_commit="abc123")
    RuntimeBundleCompiler().compile(
        registry_root / "2026.08.05.1",
        ontologies=[ontology], bindings=[binding], output=store_root,
    )

    active = RegistryArtifactStore(store_root).activate("2026.08.05.1")

    assert active.version == "2026.08.05.1"
    assert RegistryArtifactStore(store_root).load_active().manifest.version == active.version

    publish_registry(root, version="2026.08.05.2", output=registry_root, git_commit="def456")
    RuntimeBundleCompiler().compile(
        registry_root / "2026.08.05.2",
        ontologies=[ontology], bindings=[binding], output=store_root,
    )
    RegistryArtifactStore(store_root).activate("2026.08.05.2")
    rolled_back = RegistryArtifactStore(store_root).activate("2026.08.05.1")

    assert RegistryArtifactStore(store_root).load_active().manifest.version == rolled_back.version


def test_runtime_bundle_loader_rejects_modified_binding_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "core").mkdir()
    (root / "core" / "data_types.yaml").write_text(
        "registry:\n  version: 1.0.0\n  registered_at: '2026-08-05'\n"
        "data_types:\n  - id: text\n    name: Text\n    base_type: string\n",
        encoding="utf-8",
    )
    registry_root = tmp_path / "registry_dist"
    bundle_root = tmp_path / "bundle_dist"
    publish_registry(root, version="2026.08.05.1", output=registry_root, git_commit="abc123")
    RuntimeBundleCompiler().compile(
        registry_root / "2026.08.05.1", ontologies=[], bindings=[], output=bundle_root,
    )
    bundle = bundle_root / "2026.08.05.1"
    loaded = RuntimeBundleLoader(bundle).load()
    assert loaded.manifest.capability_count == 0
    assert (bundle / "capabilities.json").is_file()
    assert (bundle / "compatibility.json").is_file()
    (bundle / "bindings.json").write_text('[{"status":"approved"}]\n', encoding="utf-8")

    with pytest.raises(RegistryArtifactError, match="checksum"):
        RuntimeBundleLoader(bundle).load()


def test_runtime_bundle_loader_keeps_schema_v1_artifacts_replayable(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    (root / "core").mkdir()
    (root / "core" / "data_types.yaml").write_text(
        "registry:\n  version: 1.0.0\n  registered_at: '2026-08-05'\n"
        "data_types:\n  - id: text\n    name: Text\n    base_type: string\n",
        encoding="utf-8",
    )
    registry_root = tmp_path / "registry_dist"
    bundle_root = tmp_path / "bundle_dist"
    publish_registry(root, version="2026.08.05.1", output=registry_root, git_commit="abc123")
    RuntimeBundleCompiler().compile(
        registry_root / "2026.08.05.1", ontologies=[], bindings=[], output=bundle_root,
    )
    bundle = bundle_root / "2026.08.05.1"
    manifest_path = bundle / "bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.0"
    manifest["bundle_checksum"] = _checksum({
        "registry": manifest["registry_checksum"],
        "ontologies": manifest["ontology_checksum"],
        "bindings": manifest["binding_checksum"],
    })
    for key in ("capability_checksum", "capability_count", "compatibility_checksum"):
        manifest.pop(key)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "capabilities.json").unlink()
    (bundle / "compatibility.json").unlink()

    loaded = RuntimeBundleLoader(bundle).load()

    assert loaded.manifest.schema_version == "1.0"
    assert loaded.capabilities == []
