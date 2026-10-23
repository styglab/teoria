"""Evaluation must reject incomparable evidence and detect structural regressions."""

import copy
import json
import subprocess
import sys

import pytest

from evaluations.execution import run_process
from evaluations.runner import (
    PROJECT,
    compare_reports,
    evaluate,
    fixture_bytes,
    input_bytes,
    load_manifest,
    score,
    sha,
)

SEED = PROJECT / "evaluations/corpus/seed.json"


def test_seed_is_reproducible_and_source_oracles_pass(tmp_path):
    manifest = load_manifest(SEED)
    assert {c["split"] for c in manifest["cases"]} == {"development", "validation"}
    hashes = [c["sha256"] for c in manifest["cases"]]
    assert len(hashes) == len(set(hashes))
    for case in manifest["cases"]:
        assert sha(input_bytes(case, SEED.parent)) == case["sha256"]
    report = evaluate(SEED, tmp_path / "report")
    assert report["passed"]
    assert len(report["cases"]) == 8
    assert report["source_sha256"]
    assert report["evaluator_sha256"]
    assert "expected" not in json.dumps(report)
    assert (tmp_path / "report/report.md").exists()
    with pytest.raises(FileExistsError):
        evaluate(SEED, tmp_path / "report")


def test_corrupt_input_is_rejected_before_any_execution(tmp_path):
    data = json.loads(SEED.read_text())
    data["cases"][0]["sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        evaluate(path, tmp_path / "output", corpus_root=SEED.parent)
    assert not (tmp_path / "output").exists()


def test_input_cannot_escape_corpus_root(tmp_path):
    with pytest.raises(ValueError, match="within corpus root"):
        input_bytes({"source_path": "../private.pdf"}, tmp_path)


@pytest.mark.parametrize("change", ["duplicate", "empty", "threshold", "option", "split"])
def test_invalid_manifest_never_runs(change, tmp_path):
    data = json.loads(SEED.read_text())
    if change == "duplicate":
        data["cases"].append(data["cases"][0])
    elif change == "empty":
        data["cases"] = []
    elif change == "threshold":
        data["thresholds"] = {"text_recall": float("nan")}
    elif change == "option":
        data["cases"][0]["options"] = {"pdf_backend": "unverified"}
    else:
        data["cases"][0]["split"] = "typo"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(path)


def test_zip_generation_is_stable_across_part_order():
    assert fixture_bytes({"a": "한글", "b": "42"}) == fixture_bytes({"b": "42", "a": "한글"})


def test_reordered_text_is_not_hidden_by_character_recall():
    expected = {"success": True, "blocks": [{"type": "paragraph", "text": "AlphaBeta"}]}
    actual = {"success": True, "blocks": [{"type": "paragraph", "text": "BetaAlpha"}]}
    metrics = score(expected, actual)
    assert metrics["text_recall"] == 1
    assert metrics["reading_order"] < 1


def test_merge_change_and_contents_change_are_detected():
    expected = {
        "success": True,
        "blocks": [
            {
                "type": "table",
                "table": {
                    "rows": 1,
                    "cols": 2,
                    "cells": [[{"text": "A", "col_span": 2}, {"covered": True}]],
                },
            }
        ],
        "contents": [{"entries": [{"title": "Chapter", "level": 1}]}],
    }
    actual = copy.deepcopy(expected)
    actual["blocks"][0]["table"]["cells"][0] = [{"text": "A"}, {"text": ""}]
    actual["contents"][0]["entries"][0]["level"] = 2
    metrics = score(expected, actual)
    assert metrics["text_recall"] == 1
    assert metrics["table_structure"] == 0
    assert metrics["table_cells"] == 0
    assert metrics["contents"] == 0


def report(metrics):
    return {
        "manifest_sha256": "manifest",
        "evaluator_sha256": "eval",
        "lock_sha256": "lock",
        "python": "python",
        "dependencies": {},
        "split": "all",
        "cases": [
            {"id": "case", "input_sha256": "input", "options": {}, "metrics": metrics, "passed": False}
        ],
    }


def test_gain_cannot_mask_other_metric_regression():
    comparison = compare_reports(
        report({"text_recall": 0.8, "table_cells": 1}), report({"text_recall": 1, "table_cells": 0})
    )
    assert comparison["improvements"]
    assert comparison["regressions"]
    assert not comparison["accepted"]


def test_comparison_requires_frozen_evaluator():
    before = report({"success": 1})
    after = copy.deepcopy(before)
    after["evaluator_sha256"] = "changed"
    with pytest.raises(ValueError, match="evaluator_sha256"):
        compare_reports(before, after)


def test_worker_timeout_is_a_failed_case(monkeypatch, tmp_path):
    data = json.loads(SEED.read_text())
    data["cases"] = [data["cases"][0]]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)

    monkeypatch.setattr("evaluations.runner.run_process", timeout)
    result = evaluate(path, tmp_path / "run")
    assert not result["passed"]
    assert result["cases"][0]["error"] == "TimeoutExpired"
    assert result["cases"][0]["metrics"]["success"] == 0


def test_process_timeout_terminates_child(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time; time.sleep(20)"], cwd=tmp_path, timeout=0.1)


def test_same_document_cannot_cross_splits(tmp_path):
    data = json.loads(SEED.read_text())
    other = copy.deepcopy(data["cases"][0])
    other.update(id="duplicate_validation", split="validation")
    data["cases"].append(other)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="both splits"):
        load_manifest(path)


def test_quality_gain_does_not_override_repeated_timing_regression():
    before = report({"text_recall": 0.8})
    after = report({"text_recall": 1.0})
    before["cases"][0].update(parse_success=True, seconds=0.1)
    after["cases"][0].update(parse_success=True, seconds=0.2)
    comparison = compare_reports(before, after)
    assert comparison["improvements"]
    assert not comparison["accepted"]
    assert "aggregate_timing_regression" in comparison["regressions"]
