"""New discovery samples must not consume old documents or mutate fixed regressions."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from evaluations.public_procurement import sample as sampler
from evaluations.public_procurement.history import (
    CorpusHistory,
    digest,
    load_state,
    new_seed,
    used_notices,
    validation_plan,
)


def record(path, number="R26BK00000001", text=b"%PDF-1.4\nold"):
    path.write_bytes(text)
    return {
        "document_id": number.lower(),
        "notice_number": number,
        "notice_order": "000",
        "family": "old:goods",
        "format": "pdf",
        "source_path": str(path),
        "sha256": digest(text),
    }


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "history/state.json"
    old = record(tmp_path / "old.pdf")
    with CorpusHistory(path) as history:
        history.freeze_regression([old])
    return path, old


def frame(count=8):
    return [
        {
            "notice_number": f"R26BK0001{i:04d}",
            "notice_order": "000",
            "work_type": "goods",
            "organization_code": f"org_{i}",
            "attachments": [
                {
                    "slot": slot,
                    "file_name": f"file_{slot}.pdf",
                    "url": f"https://www.g2b.go.kr/file/{i}/{slot}",
                }
                for slot in range(1, 4)
            ],
        }
        for i in range(count)
    ]


def mock_client(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        sampler.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_new_seeds_and_explicit_reproducibility():
    assert new_seed() != new_seed()
    assert new_seed("repeat") == "repeat"
    with pytest.raises(ValueError):
        new_seed("")


def test_regression_pool_cannot_change_silently(corpus, tmp_path):
    path, old = corpus
    with CorpusHistory(path) as history:
        before = history.regression_bytes()
        later = record(tmp_path / "later.pdf", "R26BK00000002", b"%PDF-new")
        history.register([later], role="development")
        assert history.regression_bytes() == before
        with pytest.raises(ValueError, match="frozen"):
            history.freeze_regression([old, later])
        assert history.regression_bytes() == before


def test_history_serializes_sampling_writers(corpus):
    path, _ = corpus
    with CorpusHistory(path), pytest.raises(BlockingIOError), CorpusHistory(path):
        pass


def test_corrupt_history_is_not_treated_as_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"unexpected": true}')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="refuse to reset"):
        load_state(path)
    assert path.read_bytes() == before


def test_validation_families_have_no_prior_exposure():
    rows = [{"family": "seen"}, {"family": "fresh_a"}, {"family": "fresh_b"}]
    plan = validation_plan(rows, {"seen"}, "seed")
    assert plan["seen"] == "development"
    assert "validation" in plan.values()
    assert {name for name, role in plan.items() if role == "validation"} <= {"fresh_a", "fresh_b"}
    assert set(validation_plan([{"family": "seen"}], {"seen"}, "seed").values()) == {"development"}


def test_two_runs_get_new_data_and_identical_regression_pool(corpus, tmp_path, monkeypatch):
    history_path, old = corpus
    notices = frame()
    notices.append(
        {
            "notice_number": old["notice_number"],
            "notice_order": "001",
            "work_type": "goods",
            "organization_code": "old",
            "attachments": [{"slot": 1, "file_name": "old.pdf", "url": "https://www.g2b.go.kr/old"}],
        }
    )
    manifest = tmp_path / "notices.json"
    manifest.write_text(json.dumps(notices))
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, content=b"%PDF-1.4\n" + request.url.path.encode())

    mock_client(monkeypatch, handler)
    first = asyncio.run(sampler.sample(manifest, tmp_path / "first", count=3, history_path=history_path))
    second = asyncio.run(sampler.sample(manifest, tmp_path / "second", count=3, history_path=history_path))
    assert first["status"] == second["status"] == "complete"
    assert first["seed"] != second["seed"]
    assert "/old" not in requests
    before = json.loads((tmp_path / "first/manifest.json").read_text())
    after = json.loads((tmp_path / "second/manifest.json").read_text())
    assert {r["sha256"] for r in before}.isdisjoint(r["sha256"] for r in after)
    assert {r["notice_number"] for r in before}.isdisjoint(r["notice_number"] for r in after)
    assert (tmp_path / "first/regression_manifest.json").read_bytes() == (
        tmp_path / "second/regression_manifest.json"
    ).read_bytes()
    for output in ["first", "second"]:
        cycle = json.loads((tmp_path / output / "cycle_manifest.json").read_text())
        assert cycle["fresh_manifest_sha256"] == digest((tmp_path / output / "manifest.json").read_bytes())
        development = json.loads((tmp_path / output / "development_manifest.json").read_text())
        validation = json.loads((tmp_path / output / "validation_manifest.json").read_text())
        assert len(development) == 2 and len(validation) == 1
        assert {r["family"] for r in development}.isdisjoint(r["family"] for r in validation)
    assert {r["notice_number"] for r in [*before, *after]} <= used_notices(load_state(history_path))


def test_old_bytes_at_a_new_url_never_enter_validation(corpus, tmp_path, monkeypatch):
    history_path, old = corpus
    notices = frame(3)
    rows = list(sampler.selection(notices, seed="known"))
    plan = validation_plan(rows, {"old:goods"}, "known")
    validation_org = next(name.split(":")[0] for name, role in plan.items() if role == "validation")
    validation_index = validation_org.removeprefix("org_")
    manifest = tmp_path / "notices.json"
    manifest.write_text(json.dumps(notices))

    def handler(request):
        content = (
            (tmp_path / "old.pdf").read_bytes()
            if request.url.path.split("/")[2] == validation_index
            else b"%PDF-" + request.url.path.encode()
        )
        return httpx.Response(200, content=content)

    mock_client(monkeypatch, handler)
    result = asyncio.run(
        sampler.sample(manifest, tmp_path / "sample", count=2, seed="known", history_path=history_path)
    )
    assert result["status"] == "insufficient_fresh_candidates"
    selected = json.loads((tmp_path / "sample/manifest.json").read_text())
    assert old["sha256"] not in {r["sha256"] for r in selected}
    assert not json.loads((tmp_path / "sample/validation_manifest.json").read_text())
    assert any(a["status"] == "duplicate_history" for a in result["attempts"])


def test_interrupted_run_retains_use_history(corpus, tmp_path, monkeypatch):
    history_path, _ = corpus
    manifest = tmp_path / "notices.json"
    manifest.write_text(json.dumps(frame(5)))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) > 1:
            raise RuntimeError("interrupted test transport")
        return httpx.Response(200, content=b"%PDF-" + request.url.path.encode())

    mock_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="interrupted test"):
        asyncio.run(sampler.sample(manifest, tmp_path / "sample", count=3, history_path=history_path))
    selected = json.loads((tmp_path / "sample/manifest.json").read_text())
    assert len(selected) == 1
    state = load_state(history_path)
    assert selected[0]["sha256"] in state["documents"]
    assert json.loads((tmp_path / "sample/sampling.json").read_text())["status"] == "interrupted"


def test_exhausted_frame_is_not_refilled_with_old_notices(corpus, tmp_path, monkeypatch):
    history_path, old = corpus
    with CorpusHistory(history_path) as history:
        rows = [
            {**old, "notice_number": n["notice_number"], "family": f"{n['organization_code']}:goods"}
            for n in frame(3)
        ]
        history.register(rows, role="development")
    manifest = tmp_path / "notices.json"
    manifest.write_text(json.dumps(frame(3)))

    def handler(request):
        raise AssertionError("Old notices must not be downloaded")

    mock_client(monkeypatch, handler)
    result = asyncio.run(sampler.sample(manifest, tmp_path / "sample", count=2, history_path=history_path))
    assert result["status"] == "insufficient_fresh_candidates"
    assert result["sampled_count"] == 0
    assert not json.loads((tmp_path / "sample/manifest.json").read_text())


def test_fixed_regression_is_required_and_identity_bound(corpus, tmp_path):
    from evaluations.public_procurement.gate import fixed_regression_check

    history_path, _ = corpus
    state = load_state(history_path)
    pool = state["regression"]
    cycle = {
        "status": "complete",
        "fresh_manifest_sha256": "fresh",
        "datasets": {"regression": {"path": pool["path"], "sha256": pool["sha256"]}},
    }
    benchmark = {"manifest_sha256": "fresh", "source_hashes": {"baseline": "base", "candidate": "candidate"}}
    assert fixed_regression_check(cycle, benchmark, None) == "fixed_regression_replay_required"
    report = {
        "status": "complete",
        "manifest_sha256": pool["sha256"],
        "documents": 1,
        "equal_except_version": 1,
        "baseline_source_sha256": "base",
        "candidate_source_sha256": "candidate",
    }
    assert fixed_regression_check(cycle, benchmark, report) is None
    report["candidate_source_sha256"] = "other"
    assert fixed_regression_check(cycle, benchmark, report) == "fixed_regression_failed_or_identity_mismatch"
    cycle["status"] = "insufficient_fresh_candidates"
    assert fixed_regression_check(cycle, benchmark, report) == "incomplete_or_unrelated_sampling_cycle"


def test_regression_replay_records_all_inputs(corpus, tmp_path):
    from evaluations.public_procurement.regression import replay
    from evaluations.runner import PROJECT

    history_path, _ = corpus
    pool = load_state(history_path)["regression"]
    result = replay(Path(pool["path"]), PROJECT, PROJECT, tmp_path / "replay")
    assert result["status"] == "complete"
    assert result["documents"] == result["processed_documents"] == result["equal_except_version"] == 1
    assert result["manifest_sha256"] == pool["sha256"]
    assert result["identical_sources_reused"]
