"""A verified baseline parser crash is recoverable; missing execution evidence is not."""

import json
import os
import subprocess
import sys

import pytest

from evaluations.benchmark import PYTHON_WORKER
from evaluations.public_procurement.gate import assess
from evaluations.public_procurement.report import generate
from evaluations.runner import sha, write_json


@pytest.fixture
def recovery_input(tmp_path):
    directory = tmp_path / "benchmark"
    hashes = {"baseline": "old", "candidate": "new"}
    rows = []
    for identifier in ("crash", "common"):
        (directory / identifier).mkdir(parents=True)
        engines = {
            e: {"success": True, "median_seconds": 1.0, "execution_error": None, "version": "test"}
            for e in ("baseline", "candidate", "kordoc")
        }
        for e in engines:
            write_json(directory / identifier / (e + ".json"), {"success": True, "blocks": []})
        rows.append({"document_id": identifier, "engines": engines})
    (directory / "crash/baseline.json").unlink()
    rows[0]["engines"]["baseline"] = {
        "success": False,
        "median_seconds": None,
        "execution_error": "AssertionError",
        "exception_type": "AssertionError",
        "failure_kind": "parser_exception",
    }
    report = {
        "manifest_sha256": "manifest",
        "source_hashes": hashes,
        "results": rows,
        "reference_version": "test",
    }
    write_json(directory / "benchmark.json", report)
    quality = {
        "benchmark_manifest_sha256": "manifest",
        "benchmark_source_hashes": hashes,
        "improvements": ["crash:cached_cell_value_presence"],
        "regressions": [],
    }
    policy = {
        "timing": {
            "aggregate_max_ratio": 1.05,
            "per_document_ratio_warning": 1.15,
            "per_document_absolute_warning_seconds": 0.01,
            "confirmation_repetitions": 5,
        }
    }
    return directory, report, quality, policy


def test_source_checked_parser_crash_recovery_is_reported_without_fake_baseline_output(recovery_input):
    directory, _, quality, policy = recovery_input
    result = assess(directory, quality, policy)
    assert result["accepted"]
    assert result["changed_documents"] == ["crash"]
    assert result["recovered_baseline_failures"] == ["crash"]
    assert result["successful_document_median_sum_seconds"] == {"baseline": 1.0, "candidate": 1.0}
    assert not (directory / "crash/baseline.json").exists()


@pytest.mark.parametrize(
    "condition",
    [
        "startup",
        "unclassified",
        "candidate",
        "reference",
        "unreviewed",
        "missing_candidate",
        "missing_success",
        "invalid_json",
        "regression",
        "unexpected_baseline",
        "slower",
    ],
)
def test_other_failures_still_reject_without_crashing(recovery_input, condition):
    directory, report, quality, policy = recovery_input
    row = report["results"][0]
    if condition == "startup":
        row["engines"]["baseline"]["failure_kind"] = "executor_failure"
    elif condition == "unclassified":
        del row["engines"]["baseline"]["exception_type"]
    elif condition in ("candidate", "reference"):
        row["engines"]["candidate" if condition == "candidate" else "kordoc"]["execution_error"] = (
            "RuntimeError"
        )
    elif condition == "unreviewed":
        quality["improvements"] = ["other:metric"]
    elif condition == "missing_candidate":
        (directory / "crash/candidate.json").unlink()
    elif condition == "missing_success":
        (directory / "common/baseline.json").unlink()
    elif condition == "invalid_json":
        (directory / "crash/candidate.json").write_text("{")
    elif condition == "regression":
        quality["regressions"] = ["other:metric"]
    elif condition == "unexpected_baseline":
        write_json(directory / "crash/baseline.json", {"success": True})
    elif condition == "slower":
        report["results"][1]["engines"]["candidate"]["median_seconds"] = 2.0
    write_json(directory / "benchmark.json", report)
    assert not assess(directory, quality, policy)["accepted"]


@pytest.mark.parametrize("missing_source", [False, True])
def test_worker_distinguishes_parse_exception_from_input_failure(tmp_path, missing_source):
    package = tmp_path / "src/kory_parser"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        'class ParseOptions:\n def __init__(self,**kw):pass\ndef parse(*args):\n raise AssertionError("fixture")\n'
    )
    (package / "version.py").write_text('__version__="test"\n')
    source = tmp_path / "source.bin"
    if not missing_source:
        source.write_bytes(b"fixture")
    measurement, output = tmp_path / "measurement.json", tmp_path / "output.json"
    run = subprocess.run(
        [sys.executable, "-c", PYTHON_WORKER],
        check=False,
        input=json.dumps(
            {"source": str(source), "measurement": str(measurement), "output": str(output), "repetitions": 3}
        ),
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tmp_path / "src")),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert not output.exists()
    if missing_source:
        assert run.returncode != 0 and not measurement.exists()
    else:
        assert run.returncode == 0
        result = json.loads(measurement.read_text())
        assert result["failure_kind"] == "parser_exception" and result["exception_type"] == "AssertionError"
        assert "AssertionError" in run.stderr


def test_report_keeps_crash_in_denominator_and_excludes_it_from_timing(recovery_input):
    directory, _, quality, policy = recovery_input
    root = directory.parent
    (root / "sample").mkdir()
    (root / "acceptance").mkdir()
    write_json(
        root / "sample/sampling.json",
        {"sampled_count": 2, "notice_frame_count": 2, "formats": {"xls": 2}, "splits": {"development": 2}},
    )
    write_json(root / "source_labels.json", {})
    quality.update(
        labels_sha256=sha((root / "source_labels.json").read_bytes()),
        labelled_documents=1,
        totals={e: {} for e in ("baseline", "candidate", "kordoc")},
    )
    write_json(root / "quality.json", quality)
    result = assess(directory, quality, policy)
    result.update(tests_passed=True, applied=False)
    write_json(root / "acceptance/acceptance.json", result)
    summary = generate(root, root / "report", cleanup_intermediates=False)
    assert summary["success"]["baseline"] == 1 and summary["compared_documents"] == 2
    assert summary["timing_common_documents"] == 1
    assert summary["parser_exceptions"]["baseline"] == 1
    assert not (directory / "crash/baseline.json").exists()
