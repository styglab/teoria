from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


CALVER_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d+$")


class RegistryRelease(BaseModel):
    version: str
    git_commit: str
    checksum: str
    published_at: datetime
    status: Literal["published", "modified"] = "published"

    def public_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "git_commit": self.git_commit,
            "checksum": self.checksum,
            "published_at": self.published_at.isoformat(),
            "status": self.status,
        }


def calculate_registry_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.yaml")):
        relative_path = path.relative_to(root).as_posix()
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(canonical.encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def publish_registry(
    root: Path,
    *,
    version: str,
    output: Path,
    git_commit: str | None = None,
    published_at: datetime | None = None,
) -> RegistryRelease:
    if not CALVER_PATTERN.fullmatch(version):
        raise ValueError("version must use YYYY.MM.DD.REVISION format")
    commit = git_commit or _git_commit(root)
    release = RegistryRelease(
        version=version,
        git_commit=commit,
        checksum=calculate_registry_checksum(root),
        published_at=published_at or datetime.now(timezone.utc),
    )
    manifest = json.dumps(release.public_dict(), ensure_ascii=False, indent=2) + "\n"
    destination = output / version
    if destination.exists():
        raise FileExistsError(f"release output already exists: {destination}")
    shutil.copytree(root, destination / "registries", ignore=shutil.ignore_patterns(".release.json"))
    (destination / "manifest.json").write_text(manifest, encoding="utf-8")
    return release


def _git_commit(root: Path) -> str:
    try:
        repository = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        relative_root = root.resolve().relative_to(Path(repository).resolve())
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal", "--", relative_root.as_posix()],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        if status.stdout.strip():
            raise ValueError(
                "Registry has uncommitted changes; commit them before publishing "
                "or pass an explicit provenance with --git-commit"
            )
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("git commit is unavailable; pass --git-commit") from exc
    return result.stdout.strip()
