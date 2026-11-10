"""Discovery and acceptance decisions must use source evidence and fixed snapshots."""

import pytest

from evaluations.public_procurement.gate import apply_source, assess
from evaluations.public_procurement.probes import grade, source_labels
from evaluations.public_procurement.sample import allowed, file_format, selection
from evaluations.runner import fixture_bytes, sha, tree_digest, write_json


def notice(number, kind="goods"):
    return {
        "notice_number": number,
        "notice_order": "000",
        "work_type": kind,
        "organization_code": "org",
        "attachments": [
            {"slot": i, "file_name": f"file_{i}.hwpx", "url": "https://www.g2b.go.kr/file"}
            for i in range(1, 6)
        ],
    }


def test_sampling_is_reproducible_and_notice_bounded():
    frame = [notice("one"), notice("two", "service")]
    left = list(selection(frame, seed="seed"))
    assert left == list(selection(list(reversed(frame)), seed="seed"))
    assert len(left) == 6
    assert {r["work_type"] for r in left} == {"goods", "service"}
    assert [r["rank"] for r in left] != [r["rank"] for r in selection(frame, seed="another")]


def test_download_signature_and_redirect_hosts_are_checked():
    assert file_format(fixture_bytes({"Contents/section0.xml": "<sec/>"})) == "hwpx"
    assert file_format(b"%PDF-1.4") == "pdf"
    assert allowed("https://www.g2b.go.kr/file")
    assert not allowed("https://www.g2b.go.kr.evil.example/file")
    assert not allowed("http://www.g2b.go.kr/file")
    with pytest.raises(ValueError, match="unsupported_container"):
        file_format(b"<html>Error</html>")


def test_oracles_are_derived_from_original_xml(tmp_path):
    data = fixture_bytes({"word/document.xml": "<document><p><t>Original source</t></p><tbl/></document>"})
    source = tmp_path / "source.docx"
    source.write_bytes(data)
    manifest = [
        {
            "document_id": "source",
            "sha256": sha(data),
            "format": "docx",
            "split": "development",
            "source_path": str(source),
        }
    ]
    labels = source_labels(manifest, {})
    case = labels["cases"][0]
    assert case["source_fragments"] == ["Original source"]
    assert case["table_count"] == 1
    actual = {"success": True, "blocks": [{"type": "paragraph", "text": "Wrong text"}]}
    scores = grade(case, actual)
    assert scores["source_fragment_presence"] == {"passed": 0, "total": 1}
    assert scores["xml_table_count"] == {"passed": 0, "total": 1}


@pytest.fixture
def gate_input(tmp_path):
    directory = tmp_path / "benchmark"
    (directory / "doc").mkdir(parents=True)
    before = {"success": True, "blocks": [], "parser_version": "old"}
    after = {"success": True, "blocks": [{"type": "paragraph", "text": "Recovered"}], "parser_version": "new"}
    write_json(directory / "doc/baseline.json", before)
    write_json(directory / "doc/candidate.json", after)
    hashes = {"baseline": "old", "candidate": "new"}
    row = {
        "document_id": "doc",
        "sha256": "input",
        "engines": {
            name: {"success": True, "median_seconds": seconds, "execution_error": None}
            for name, seconds in [("baseline", 1.0), ("candidate", 0.8), ("kordoc", 1.2)]
        },
    }
    report = {"source_hashes": hashes, "manifest_sha256": "manifest", "results": [row], "repetitions": 3}
    write_json(directory / "benchmark.json", report)
    quality = {
        "benchmark_manifest_sha256": "manifest",
        "benchmark_source_hashes": hashes,
        "regressions": [],
        "improvements": ["doc:reviewed_pdf_page_grid"],
    }
    policy = {
        "timing": {
            "aggregate_max_ratio": 1.05,
            "per_document_ratio_warning": 1.15,
            "per_document_absolute_warning_seconds": 0.01,
            "confirmation_repetitions": 5,
        }
    }
    return directory, quality, policy, report


def test_acceptance_needs_improvement_and_no_regression(gate_input):
    directory, quality, policy, _ = gate_input
    assert assess(directory, quality, policy)["accepted"]
    quality["improvements"] = []
    assert not assess(directory, quality, policy)["accepted"]
    quality["improvements"] = ["doc:grid"]
    quality["regressions"] = ["doc:missing_text"]
    assert not assess(directory, quality, policy)["accepted"]


def test_timing_regression_blocks_otherwise_better_output(gate_input):
    directory, quality, policy, report = gate_input
    report["results"][0]["engines"]["candidate"]["median_seconds"] = 1.3
    write_json(directory / "benchmark.json", report)
    result = assess(directory, quality, policy)
    assert not result["accepted"]
    assert "aggregate_timing_regression_or_unavailable" in result["failures"]


def test_quality_evidence_cannot_be_reused_for_another_candidate(gate_input):
    directory, quality, policy, _ = gate_input
    quality["benchmark_source_hashes"] = {"baseline": "old", "candidate": "different"}
    with pytest.raises(ValueError, match="identity mismatch"):
        assess(directory, quality, policy)


def test_apply_requires_exact_baseline_and_candidate_snapshots(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    for root, text in [(project, "old"), (candidate, "new")]:
        (root / "src").mkdir(parents=True)
        (root / "src/parser.py").write_text(text)
    hashes = {"baseline": tree_digest(project / "src"), "candidate": tree_digest(candidate / "src")}
    (project / "src/parser.py").write_text("someone else changed this")
    with pytest.raises(ValueError, match="Source changed"):
        apply_source(project, candidate, hashes)
    assert (project / "src/parser.py").read_text() == "someone else changed this"
    (project / "src/parser.py").write_text("old")
    apply_source(project, candidate, hashes)
    assert (project / "src/parser.py").read_text() == "new"
