"""Exercise publication against local Git remotes without touching GitHub."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def git(*args, cwd, env):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def publication(tmp_path):
    env = dict(os.environ, GIT_AUTHOR_NAME="Publication Test", GIT_COMMITTER_NAME="Publication Test",
               GIT_AUTHOR_EMAIL="publication@example.test", GIT_COMMITTER_EMAIL="publication@example.test")
    remote = tmp_path / "remote with spaces.git"
    git("init", "--bare", "--initial-branch=main", str(remote), cwd=tmp_path, env=env)
    seed = tmp_path / "seed"
    git("clone", str(remote), str(seed), cwd=tmp_path, env=env)
    (seed / "README.md").write_text("old content\n")
    (seed / "obsolete.py").write_text("old implementation\n")
    git("add", ".", cwd=seed, env=env)
    git("commit", "-m", "Seed remote", cwd=seed, env=env)
    git("push", "origin", "main", cwd=seed, env=env)

    archive = tmp_path / "teoria with spaces/archive"
    source = archive / "kory_parser"
    source.mkdir(parents=True)
    for directory in ("src", "docs", "third_party", "evaluations", ".venv", ".artifacts"):
        (source / directory).mkdir()
        (source / directory / "example.txt").write_text("fixture\n")
    (source / "src/__pycache__").mkdir()
    (source / "src/__pycache__/cached.pyc").write_bytes(b"cache")
    for name in ("README.md", "pyproject.toml", "uv.lock", "LICENSE", "NOTICE"):
        (source / name).write_text("new " + name + "\n")
    (source / ".gitignore").write_text("__pycache__/\n.venv/\n")
    script = archive / "publish_kory_parser.sh"
    shutil.copy2(Path(__file__).resolve().parents[3] / script.name, script)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env["TMPDIR"] = str(temporary)

    def run(*args):
        return subprocess.run(
            ["bash", str(script), "--remote", str(remote), *args],
            cwd=tmp_path, env=env, text=True, capture_output=True,
        )

    return remote, source, temporary, env, run


def test_preview_leaves_remote_and_source_unchanged(publication):
    remote, source, temporary, env, run = publication
    before = git("rev-parse", "main", cwd=remote, env=env)
    result = run()
    assert result.returncode == 0, result.stderr
    assert "Preview only" in result.stdout
    assert git("rev-parse", "main", cwd=remote, env=env) == before
    assert (source / "README.md").read_text() == "new README.md\n"
    assert not list(temporary.iterdir())


def test_push_mirrors_parser_without_evaluation_or_local_artifacts(publication):
    remote, _, temporary, env, run = publication
    result = run("--push", "--message", "Publish parser fixture")
    assert result.returncode == 0, result.stderr
    files = git("ls-tree", "-r", "--name-only", "main", cwd=remote, env=env).splitlines()
    assert "src/example.txt" in files
    assert "obsolete.py" not in files
    assert not any(name.startswith(("evaluations/", ".venv/", ".artifacts/")) or "__pycache__" in name
                   for name in files)
    assert git("show", "main:README.md", cwd=remote, env=env) == "new README.md"
    repeat = run("--push")
    assert repeat.returncode == 0, repeat.stderr
    assert "No parser changes" in repeat.stdout
    assert not list(temporary.iterdir())


def test_pr_branch_does_not_update_main(publication):
    remote, _, temporary, env, run = publication
    before = git("rev-parse", "main", cwd=remote, env=env)
    result = run("--push", "--branch", "parser-fix")
    assert result.returncode == 0, result.stderr
    assert git("rev-parse", "main", cwd=remote, env=env) == before
    assert git("show", "parser-fix:README.md", cwd=remote, env=env) == "new README.md"
    assert not list(temporary.iterdir())


def test_rejected_push_reports_failure_and_removes_temporary_clone(publication):
    remote, _, temporary, env, run = publication
    before = git("rev-parse", "main", cwd=remote, env=env)
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    result = run("--push")
    assert result.returncode != 0
    assert "Uploaded" not in result.stdout
    assert git("rev-parse", "main", cwd=remote, env=env) == before
    assert not list(temporary.iterdir())
