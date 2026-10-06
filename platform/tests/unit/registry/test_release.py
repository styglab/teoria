import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from teoria.registry.release import calculate_registry_checksum, load_registry_release, publish_registry
from teoria.registry.artifact import (
    RegistryArtifactError,
    RegistryArtifactLoader,
    RegistryArtifactStore,
    RuntimeBundleCompiler,
    RuntimeBundleLoader,
)


def test_publish_uses_calver_and_detects_registry_changes(tmp_path: Path) -> None:
    root = tmp_path / "registries"
    root.mkdir()
    registry = root / "example.yaml"
    registry.write_text("value: 1\n", encoding="utf-8")

    release = publish_registry(
        root,
        version="2026.08.05.1",
        git_commit="abc123",
        published_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )

    assert release.checksum == calculate_registry_checksum(root)
    assert json.loads((root / ".release.json").read_text())["version"] == "2026.08.05.1"
    assert load_registry_release(root).status == "published"

    registry.write_text("value: 2\n", encoding="utf-8")
    assert load_registry_release(root).status == "modified"


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
    RuntimeBundleLoader(bundle).load()
    (bundle / "bindings.json").write_text('[{"status":"approved"}]\n', encoding="utf-8")

    with pytest.raises(RegistryArtifactError, match="checksum"):
        RuntimeBundleLoader(bundle).load()
