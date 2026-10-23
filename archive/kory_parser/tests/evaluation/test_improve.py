"""Exercise real isolated repair/evaluation with a deterministic fake Codex executable."""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

from evaluations import improve as loop
from evaluations.runner import PROJECT, fixture_bytes, sha


@pytest.fixture
def repair_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    for directory in ("src", "evaluations", "third_party"):
        shutil.copytree(
            PROJECT / directory, project / directory, ignore=shutil.ignore_patterns("__pycache__")
        )
    (project / "tests").mkdir()
    (project / "docs").mkdir()
    for name in ("pyproject.toml", "uv.lock", "LICENSE", "NOTICE"):
        shutil.copy2(PROJECT / name, project / name)
    api = project / "src/kory_parser/api.py"
    original = api.read_text()
    api.write_text(
        original + "\n# injected_defect\n_original_parse = parse\n"
        "def parse(*args, **kwargs):\n"
        '    return ParseResult(False, "docx", error_code="INVALID_FILE")\n'
    )
    seed = json.loads((PROJECT / "evaluations/corpus/seed.json").read_text())
    dev = copy.deepcopy(seed["cases"][0])
    valid = copy.deepcopy(dev)
    valid.update(id="validation_document", split="validation")
    valid["parts"]["word/document.xml"] = valid["parts"]["word/document.xml"].replace("First", "Third")
    valid["expected"]["blocks"][0]["text"] = "Third section"
    valid["sha256"] = sha(fixture_bytes(valid["parts"]))
    seed["cases"] = [dev, valid]
    manifest = project / "evaluations/corpus/seed.json"
    manifest.write_text(json.dumps(seed))
    (project / "tests/test_public_api.py").write_text(
        "from kory_parser import ParseOptions\ndef test_options():\n    assert not ParseOptions().ocr\n"
    )
    regression = (
        "import io, zipfile\nfrom kory_parser import parse\n"
        "def test_regression():\n"
        "    stream = io.BytesIO()\n"
        '    with zipfile.ZipFile(stream, "w") as archive:\n'
        '        archive.writestr("word/document.xml", '
        '\'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Example</w:t></w:r></w:p></w:body></w:document>')\n"
        "    assert parse(stream.getvalue()).success\n"
    )
    executor = tmp_path / "fake_codex"
    executor.write_text(
        f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        'root = Path(sys.argv[sys.argv.index("--cd") + 1])\n'
        'api = root / "src/kory_parser/api.py"\n'
        'api.write_text(api.read_text().split("\\n# injected_defect")[0])\n'
        f'(root / "tests/test_added_regression.py").write_text({regression!r})\n'
        'print("completed")\n'
    )
    executor.chmod(0o755)
    monkeypatch.setattr(loop, "PROJECT", project)
    # The sdist tests must not require a repository-level installed skill.
    skill = tmp_path / "SKILL.md"
    skill.write_text("---\nname: test-repair\ndescription: Test repair.\n---\nRepair one parser defect.\n")
    monkeypatch.setattr(loop, "SKILL", skill)
    return project, manifest, executor, original


def test_repair_is_evaluated_and_saved_without_modifying_original(repair_project, tmp_path):
    project, manifest, executor, original = repair_project
    before = (project / "src/kory_parser/api.py").read_bytes()
    result = loop.improve(manifest, tmp_path / "run", iterations=2, seconds=60, executor=str(executor))
    assert result["stop_reason"] == "all_checks_passed"
    assert result["attempts"][0]["accepted"]
    candidate = Path(result["accepted_candidate"])
    assert (candidate / "src/kory_parser/api.py").read_text() == original
    assert (project / "src/kory_parser/api.py").read_bytes() == before
    assert not (candidate / "evaluations/corpus/seed.json").exists()
    development = json.loads((candidate / "evaluations/corpus/development.json").read_text())
    assert all(c["split"] == "development" for c in development["cases"])
    assert (tmp_path / "run/loop.md").exists()


def test_protected_oracle_change_stops_loop(repair_project, tmp_path):
    _, manifest, executor, _ = repair_project
    text = executor.read_text()
    executor.write_text(text + '(root / "uv.lock").write_text("tampered")\n')
    result = loop.improve(manifest, tmp_path / "run", seconds=60, executor=str(executor))
    assert result["stop_reason"] == "protected_files_changed"
    assert result["accepted_candidate"] is None


def test_no_progress_stops_at_patience(repair_project, tmp_path):
    _, manifest, executor, _ = repair_project
    executor.write_text(f'#!{sys.executable}\nprint("no change")\n')
    result = loop.improve(
        manifest, tmp_path / "run", iterations=4, patience=2, seconds=60, executor=str(executor)
    )
    assert result["stop_reason"] == "no_progress"
    assert len(result["attempts"]) == 2


def test_dry_run_never_calls_executor(repair_project, tmp_path):
    _, manifest, _, _ = repair_project
    result = loop.improve(manifest, tmp_path / "run", dry_run=True, executor="missing_codex")
    assert result["stop_reason"] == "dry_run"
    assert result["attempts"] == []


def test_budget_timeout_is_recorded(repair_project, tmp_path):
    _, manifest, executor, _ = repair_project
    executor.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(20)\n")
    result = loop.improve(manifest, tmp_path / "run", iterations=3, seconds=1, executor=str(executor))
    assert result["stop_reason"] == "time_budget"
    assert (tmp_path / "run/loop.json").exists()
    assert result["accepted_candidate"] is None


def test_missing_validation_is_rejected_before_execution(repair_project, tmp_path):
    _, manifest, _, _ = repair_project
    data = json.loads(manifest.read_text())
    data["cases"] = [data["cases"][0]]
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="both development and validation"):
        loop.improve(manifest, tmp_path / "run")


def test_codex_command_preserves_sandbox_and_no_shell(tmp_path):
    command = loop.codex_command("codex", tmp_path / "path with spaces", None)
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--cd") + 1] == str(tmp_path / "path with spaces")
    assert "--dangerously-bypass-approvals-and-sandbox" not in command


def test_validation_regression_rejects_development_gain(repair_project, tmp_path):
    project, manifest, executor, original = repair_project
    # Validation must pass before the repair to test an actual regression.
    (project / "src/kory_parser/api.py").write_text(
        original + "\n# injected_defect\n_original_parse = parse\n"
        "def parse(*args, **kwargs):\n"
        "    result = _original_parse(*args, **kwargs)\n"
        '    if result.blocks and result.blocks[0].text == "First section":\n'
        "        result.success = False\n"
        "    return result\n"
    )
    defect = (
        "\n_repaired_parse = parse\n"
        "def parse(*args, **kwargs):\n"
        "    result = _repaired_parse(*args, **kwargs)\n"
        '    if result.blocks and result.blocks[0].text == "Third section":\n'
        "        result.success = False\n"
        "    return result\n"
    )
    executor.write_text(
        executor.read_text().replace("Example", "First section")
        + f"api.write_text(api.read_text() + {defect!r})\n"
    )
    result = loop.improve(manifest, tmp_path / "run", patience=1, seconds=60, executor=str(executor))
    assert result["stop_reason"] == "no_progress"
    assert result["accepted_candidate"] is None
    assert result["attempts"][0]["improvements"]
    assert "validation_document:success" in result["attempts"][0]["regressions"]


def test_unrelated_new_test_cannot_justify_repair(repair_project, tmp_path):
    _, manifest, executor, _ = repair_project
    executor.write_text(
        executor.read_text()
        + '(root / "tests/test_added_regression.py").write_text("def test_unrelated():\\n    assert True\\n")\n'
    )
    result = loop.improve(manifest, tmp_path / "run", patience=1, seconds=60, executor=str(executor))
    assert result["accepted_candidate"] is None
    assert result["attempts"][0]["reason"] == "regression_test_did_not_reproduce"


def test_existing_test_change_is_rejected(repair_project, tmp_path):
    _, manifest, executor, _ = repair_project
    executor.write_text(executor.read_text() + '(root / "tests/test_public_api.py").write_text("")\n')
    result = loop.improve(manifest, tmp_path / "run", seconds=60, executor=str(executor))
    assert result["stop_reason"] == "protected_files_changed"
