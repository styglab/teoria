import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ROOT = Path(__file__).parents[3]
SCRIPTS = ROOT / ".agents/skills/improve-bid-eligibility/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_sample_runner_isolates_not_ready_cases_and_conceals_output(tmp_path: Path) -> None:
    module = _load("extract_sampled_cases")
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"seed": "seed", "candidates": [
        {"notice_number": "ready", "notice_order": "000", "document_count": 1,
         "unavailable_count": 0, "unsupported_count": 0},
        {"notice_number": "missing", "notice_order": "000", "document_count": 1,
         "unavailable_count": 1, "unsupported_count": 0},
    ]}))
    output = tmp_path / "outputs"
    store = MagicMock()
    store.list_notices_for_eligibility_extraction.return_value = [{
        "notice_number": "ready", "notice_order": "000",
    }]
    result = {"requirements": [], "unresolved_candidates": [], "expression": {}}
    evaluation = {"extraction": result, "source_input": {"documents": []}}
    args = argparse.Namespace(sample=sample, partition="discovery", output_dir=output,
                              max_cases=None)
    with (
        patch.object(module, "bootstrap_pipeline_settings", return_value=MagicMock()),
        patch.object(module, "PostgresStore", return_value=store),
        patch.object(module.extract_bid_eligibility_notice, "fn",
                     AsyncMock(return_value=evaluation)),
    ):
        return_code = await module.run(args)

    manifest = json.loads((output / "manifest.json").read_text())
    assert return_code == 1
    assert [item["status"] for item in manifest["cases"]] == [
        "completed_unrevealed", "not_extraction_ready",
    ]
    pending = output / manifest["cases"][0]["pending_output"]
    assert pending.stat().st_mode & 0o777 == 0


@pytest.mark.asyncio
async def test_sample_runner_records_sanitized_failure_diagnostics(tmp_path: Path) -> None:
    module = _load("extract_sampled_cases")
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"seed": "seed", "candidates": [
        {"notice_number": "failed", "notice_order": "000"},
    ]}))
    output = tmp_path / "outputs"
    store = MagicMock()
    store.list_notices_for_eligibility_extraction.return_value = [{
        "notice_number": "failed", "notice_order": "000",
    }]
    args = argparse.Namespace(sample=sample, partition="discovery", output_dir=output,
                              max_cases=None)
    with (
        patch.object(module, "bootstrap_pipeline_settings", return_value=MagicMock()),
        patch.object(module, "PostgresStore", return_value=store),
        patch.object(module.extract_bid_eligibility_notice, "fn",
                     AsyncMock(side_effect=TypeError(
                         "bad value at https://example.test/path?api_key=secret\nnext"
                     ))),
    ):
        assert await module.run(args) == 1

    failure = json.loads((output / "manifest.json").read_text())["cases"][0]
    assert failure["error_code"] == "TypeError"
    assert failure["error_message"] == "bad value at https://example.test/path?<redacted> next"
    assert "secret" not in json.dumps(failure)


def test_source_review_rejects_incomplete_expected_requirement(tmp_path: Path,
                                                               monkeypatch) -> None:
    module = _load("seal_source_review")
    review = tmp_path / "case.json"
    review.write_text(json.dumps({
        "case_id": "incomplete_review", "partition": "discovery",
        "notice": {"notice_number": "sample", "notice_order": "000"},
        "provenance": {
            "sampled_at": "2026-08-13T00:00:00+00:00",
            "input_fingerprint": "sha256:x", "versions": {},
            "expectation_method": "independent_source_review",
        },
        "expected": {
            "requirements": [{"type": "procurement_registration", "operator": "exists"}],
            "unresolved_candidates": [],
        },
        "classification": {"earliest_layer": "none", "severity": "none"},
    }))
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"documents": [], "structured_requirements": []}))
    seal = tmp_path / "seal.json"
    monkeypatch.setattr("sys.argv", [
        "seal_source_review", "--case", str(review),
        "--source-input", str(source), "--seal", str(seal),
    ])

    with pytest.raises(ValueError, match="incomplete_expected_requirement"):
        module.main()

    assert not seal.exists()


def test_source_review_must_be_sealed_before_reveal(tmp_path: Path, monkeypatch) -> None:
    seal_module = _load("seal_source_review")
    reveal_module = _load("reveal_extractions")
    review = tmp_path / "case_000.json"
    fixture = ROOT / "pipelines/tests/fixtures/bid_eligibility_evaluation/selection_explicit_bid_outcome_late_block.json"
    review.write_bytes(fixture.read_bytes())
    seal = tmp_path / "case_000.seal.json"
    source_payload = json.dumps({"documents": [{
        "document_id": "36d105e0-f846-5c29-99f7-2ee6b5d98dc65",
        "content": {"blocks": [{
            "block_id": "p29", "text": "본 용역의 전부를 제3자에게 하도급 할 수 없다.",
        }]},
    }], "structured_requirements": []})
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    source_input = output_dir / "source.json"
    source_input.write_text(source_payload)
    pending = output_dir / ".case_000.pending.json"
    pending.write_text("{}")
    os.chmod(pending, 0)
    manifest = output_dir / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{
        "notice_number": "R26BK01677837", "notice_order": "000",
        "status": "completed_unrevealed", "pending_output": pending.name,
        "source_input": source_input.name,
    }]}))

    monkeypatch.setattr("sys.argv", ["seal_source_review", "--case", str(review),
                                    "--source-input", str(source_input),
                                    "--seal", str(seal)])
    assert seal_module.main() == 0
    monkeypatch.setattr("sys.argv", ["reveal_extractions", "--manifest", str(manifest),
                                    "--reviews-dir", str(tmp_path)])
    assert reveal_module.main() == 1

    review.rename(tmp_path / "R26BK01677837_000.json")
    seal.rename(tmp_path / "R26BK01677837_000.seal.json")
    assert reveal_module.main() == 0
    revealed = json.loads(manifest.read_text())
    assert revealed["cases"][0]["status"] == "completed"
    assert (output_dir / "R26BK01677837_000.json").exists()


def test_comparator_requires_seal_manifest_and_checks_expression(tmp_path: Path,
                                                                 monkeypatch) -> None:
    module = _load("compare_extractions")
    case = tmp_path / "case.json"
    case.write_text(json.dumps({
        "case_id": "comparison_case", "partition": "discovery",
        "notice": {"notice_number": "sample", "notice_order": "000", "work_type": "service"},
        "provenance": {
            "sampled_at": "2026-08-13T00:00:00+00:00", "input_fingerprint": "sha256:x",
            "versions": {}, "expectation_method": "independent_source_review",
        },
        "expected": {
            "requirements": [], "unresolved_candidates": [],
            "expression": {"operator": "all", "requirement_id": None, "conditions": []},
        },
        "classification": {"earliest_layer": "none", "severity": "none"},
    }))
    seal = tmp_path / "case.seal.json"
    seal.write_text(json.dumps({
        "case_id": "comparison_case", "sha256": hashlib.sha256(case.read_bytes()).hexdigest(),
    }))
    actual = tmp_path / "sample_000.json"
    actual.write_text(json.dumps({
        "schema_version": "1.3.0", "requirements": [],
        "expression": {"operator": "all", "requirement_id": None, "conditions": []},
        "unresolved_candidates": [],
    }))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{
        "notice_number": "sample", "notice_order": "000", "status": "completed",
        "output": actual.name,
    }]}))
    report = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", [
        "compare_extractions", "--case", str(case), "--seal", str(seal),
        "--actual", str(actual), "--manifest", str(manifest), "--report", str(report),
    ])

    assert module.main() == 0
    value = json.loads(report.read_text())
    assert value["expression_matches"] is True
    assert value["integrity_errors"] == []


def test_comparator_detects_evidence_and_proof_mismatches() -> None:
    module = _load("compare_extractions")
    expected = [{
        "type": "custom",
        "evidence": [{"source_type": "document", "excerpt": "원문 근거"}],
        "proof_requirements": [{"document_type": "확인서", "mandatory": True}],
    }]
    actual = [{
        "type": "custom",
        "evidence": [{"source_type": "document", "excerpt": "다른 근거"}],
        "proof_requirements": [{"document_type": "확인서", "mandatory": False}],
    }]

    missing, unexpected, matched = module._match_requirements(expected, actual)

    assert matched == 0
    assert len(missing) == 1
    assert len(unexpected) == 1


def test_comparator_pairs_same_evidence_fact_and_reports_field_differences() -> None:
    module = _load("compare_extractions")
    evidence = [{
        "source_type": "document", "document_id": "doc", "block_id": "b1",
        "excerpt": "입찰서 제출 마감일 전일까지 등록한 자",
    }]
    expected = [{
        "type": "procurement_registration", "operator": "exists",
        "value": {"text": "입찰참가자격등록"}, "reference_date_type": "bid_deadline",
        "evidence": evidence,
    }]
    actual = [{
        "id": "r1", "type": "procurement_registration", "operator": "valid_on",
        "value": {"text": "조달청 입찰참가자격 등록"},
        "reference_date_type": "qualification_registration_deadline",
        "evidence": evidence,
    }]

    paired, missing, unexpected = module._pair_requirements(expected, actual)

    assert missing == []
    assert unexpected == []
    assert paired[0]["matching_basis"] == "same_type_and_evidence"
    assert set(paired[0]["field_differences"]) == {
        "operator", "value", "reference_date_type",
    }
