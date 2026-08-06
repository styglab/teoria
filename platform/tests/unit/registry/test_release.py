import json
from datetime import datetime, timezone
from pathlib import Path

from teoria.registry.release import calculate_registry_checksum, load_registry_release, publish_registry


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
