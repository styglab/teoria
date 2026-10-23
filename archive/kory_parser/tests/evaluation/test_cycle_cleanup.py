"""Cleanup must preserve fixed originals, unfinished samples and review evidence."""

from evaluations.public_procurement import cleanup
from evaluations.public_procurement.history import CorpusHistory, digest
from evaluations.runner import write_json


def test_removal_never_deletes_an_ancestor_of_a_protected_source(tmp_path):
    environment = tmp_path / "install_wheel"
    environment.mkdir()
    original = environment / "original.pdf"
    original.write_bytes(b"%PDF-original")
    result = cleanup.remove_paths([environment], {original.resolve()}, apply=True)
    assert result[0]["status"] == "protected_source"
    assert original.read_bytes() == b"%PDF-original"


def test_planning_does_not_remove_generated_files(tmp_path):
    generated = tmp_path / "install_base"
    generated.mkdir()
    (generated / "library.so").write_bytes(b"generated")
    result = cleanup.remove_paths([generated], set(), apply=False)
    assert result[0]["status"] == "planned" and generated.exists()
    result = cleanup.remove_paths([generated], set(), apply=True)
    assert result[0]["status"] == "removed" and not generated.exists()


def test_cleanup_requires_a_finished_cycle(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = project / ".artifacts/cycle"
    root.mkdir(parents=True)
    monkeypatch.setattr(cleanup, "PROJECT", project)
    sample = root / "original.pdf"
    sample.write_bytes(b"%PDF-pending")
    assert cleanup.cleanup_cycle(root, apply=True)["status"] == "not_finished"
    (root / "acceptance").mkdir()
    (root / "report").mkdir()
    write_json(root / "acceptance/acceptance.json", {"accepted": True, "applied": False})
    write_json(root / "report/summary.json", {})
    assert cleanup.cleanup_cycle(root, apply=True)["status"] == "not_finished"
    assert sample.exists()


def test_finished_cycle_only_drops_unneeded_successful_samples(tmp_path, monkeypatch):
    project = tmp_path / "project"
    root = project / ".artifacts/cycle"
    sample = root / "sample"
    sample.mkdir(parents=True)
    rows = []
    for name in ["fixed", "labelled", "problem", "failed", "unused"]:
        source = sample / (name + ".pdf")
        data = b"%PDF-" + name.encode()
        source.write_bytes(data)
        rows.append(
            {"document_id": name, "source_path": str(source), "sha256": digest(data), "format": "pdf"}
        )
    history = project / ".artifacts/history/state.json"
    with CorpusHistory(history) as state:
        state.freeze_regression([rows[0]])
        state.register(rows[1:], role="development")
    (root / "acceptance").mkdir()
    write_json(
        root / "acceptance/acceptance.json", {"accepted": True, "applied": True, "changed_documents": []}
    )
    (root / "report").mkdir()
    write_json(root / "report/summary.json", {"accepted": True})
    (root / "benchmark").mkdir()
    write_json(
        root / "benchmark/benchmark.json",
        {
            "results": [
                {
                    "document_id": r["document_id"],
                    "engines": {"candidate": {"success": r["document_id"] != "failed"}},
                }
                for r in rows
            ]
        },
    )
    write_json(sample / "manifest.json", rows)
    write_json(root / "source_labels.json", {"cases": [{"document_id": "labelled"}]})
    write_json(root / "next_issues.json", [{"document_id": "problem"}])
    (root / "discovery").mkdir()
    (root / "discovery/generated.json").write_text("{}")
    monkeypatch.setattr(cleanup, "PROJECT", project)
    result = cleanup.cleanup_cycle(root, apply=True, history_path=history)
    assert result["status"] == "cleaned"
    for name in ["fixed", "labelled", "problem", "failed"]:
        assert (sample / (name + ".pdf")).exists()
    assert not (sample / "unused.pdf").exists()
    assert not (root / "discovery").exists()
    assert (root / "acceptance/acceptance.json").exists()
    assert (root / "report/summary.json").exists()
    with CorpusHistory(history) as state:
        assert len(state.state["documents"]) == 5
        assert state.state["documents"][rows[-1]["sha256"]]["retention"] == "removed_after_completed_cycle"
