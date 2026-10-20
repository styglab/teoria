"""Offline initial dictionary pipeline: prepare, collect, build, check, approve.

Reuses qualification, composition and evidence modules. Codex authors the semantic
files between commands; this module never calls a model, DB or Platform Runtime.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import hashlib
import json
from pathlib import Path
import shutil

from pydantic import Field

from .composition_analysis import ANALYSIS_INSTRUCTIONS, CompositionProposal, write_json
from .dictionary_draft import (
    AnalysisInput, CONSOLIDATION_INSTRUCTIONS, ConsolidationProposal, build_dictionary_draft,
)
from .dictionary_review import (
    FINAL_REVIEW_INSTRUCTIONS, FinalReview, approve_offline_dictionary, validate_final_review,
)
from .document_evidence import build_document_evidence
from .document_qualification import QualificationRecord, validate_qualification_submission
from .requirement_discovery import (
    DISCOVERY_INSTRUCTIONS, DiscoveryProposal, Record, validate_discovery,
)


class SourceInput(Record):
    document_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    notice_number: str = Field(min_length=1)
    source_path: str
    native_path: str
    qualification_path: str
    parse_record_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualification_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class BatchRequest(Record):
    batch_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    documents: list[SourceInput] = Field(min_length=10, max_length=10)


class AnalysisFiles(Record):
    document_id: str
    composition_path: str
    discovery_path: str


class AnalysisBatchRequest(Record):
    prepared_batch: str
    documents: list[AnalysisFiles] = Field(min_length=10, max_length=10)
    approved_base_path: str | None = None


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path):
    return json.loads(path.read_bytes())


@contextmanager
def _new_directory(path: Path):
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield
    except BaseException:
        shutil.rmtree(path)
        raise


def _verified_document(entry: dict, files: dict[str, bytes]):
    for kind, raw in files.items():
        if sha(raw) != entry[f"{kind}_sha256"]:
            raise ValueError(f"{entry['document_id']}:{kind} hash mismatch")
    parse_record = json.loads(files["parse_record"])
    if isinstance(parse_record, list):
        matching = [r for r in parse_record if r.get("document_id") == entry["document_id"]]
        if len(matching) != 1:
            raise ValueError("parse record must uniquely identify the document")
        parse_record = matching[0]
    if (parse_record.get("document_id") != entry["document_id"] or parse_record.get("parser") != "kordoc"
            or not parse_record.get("version") or parse_record.get("status") != "success"
            or parse_record.get("options", {}).get("ocr") is not False
            or parse_record.get("options", {}).get("formulaOcr") is not False):
        raise ValueError("successful kordoc record with both OCR options disabled required")
    record = QualificationRecord.model_validate_json(files["qualification"])
    submission = record.submission
    if submission.document_id != entry["document_id"] or submission.source_sha256 != entry["source_sha256"]:
        raise ValueError("qualification does not match original source")
    document = build_document_evidence(json.loads(files["native"]), document_id=entry["document_id"],
                                       parse_run_id=submission.parse_run_id, native_sha256=sha(files["native"]))
    recomputed = validate_qualification_submission(submission, document)
    if record != recomputed or record.result.decision != "REQUIREMENTS_FOUND" or record.result.document_role not in {
            "procurement_specification", "statement_of_work", "mixed"}:
        raise ValueError("document is not a valid specification candidate")
    return document


def _check_unique_batch(entries: list[dict]) -> None:
    if len(entries) != 10:
        raise ValueError("a batch requires exactly 10 qualified and parsed notices")
    for field in ["document_id", "notice_number", "source_sha256", "native_sha256"]:
        if len({e[field] for e in entries}) != 10:
            raise ValueError(f"batch repeats {field}")


def prepare_batch(request: BatchRequest, output: Path) -> None:
    entries = [d.model_dump() for d in request.documents]
    _check_unique_batch(entries)
    loaded = []
    for entry in entries:
        files = {kind: Path(entry[f"{kind}_path"]).read_bytes()
                 for kind in ["source", "native", "qualification", "parse_record"]}
        loaded.append((entry, files, _verified_document(entry, files)))
    with _new_directory(output):
        snapshots = []
        for entry, files, document in loaded:
            directory = output / "documents" / entry["document_id"]
            directory.mkdir(parents=True)
            snapshot = {k: v for k, v in entry.items() if not k.endswith("_path")}
            for kind, raw in files.items():
                file_name = "original" + Path(entry["source_path"]).suffix if kind == "source" else f"{kind}.json"
                relative = Path("documents") / entry["document_id"] / file_name
                (output / relative).write_bytes(raw)
                snapshot[f"{kind}_file"] = str(relative)
            snapshots.append(snapshot)
            write_json(directory / "context.json", {
                "composition_instructions": ANALYSIS_INSTRUCTIONS,
                "discovery_instructions": DISCOVERY_INSTRUCTIONS, "source": document.context(),
                "source_sha256": entry["source_sha256"],
                "qualification": json.loads(files["qualification"]),
                "composition_schema": CompositionProposal.model_json_schema(),
                "discovery_schema": DiscoveryProposal.model_json_schema(),
            })
        write_json(output / "batch.json", {"schema_version": "bootstrap_batch_v1",
                                           "batch_id": request.batch_id, "documents": snapshots})
        write_json(output / "analysis_request_template.json", {
            "prepared_batch": str(output.resolve()), "approved_base_path": None,
            "documents": [{"document_id": e["document_id"],
                           "composition_path": str((output / "documents" / e["document_id"] / "composition.json").resolve()),
                           "discovery_path": str((output / "documents" / e["document_id"] / "discovery.json").resolve())}
                          for e in snapshots]})


def load_batch(directory: Path) -> tuple[dict, list, str]:
    raw = (directory / "batch.json").read_bytes()
    batch = json.loads(raw)
    _check_unique_batch(batch["documents"])
    documents = []
    for entry in batch["documents"]:
        files = {}
        for kind in ["source", "native", "qualification", "parse_record"]:
            path = (directory / entry[f"{kind}_file"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("snapshot file leaves prepared batch")
            files[kind] = path.read_bytes()
        documents.append(_verified_document(entry, files))
    return batch, documents, sha(raw)


def _load_analyses(batch_dir: Path, rows: list[AnalysisFiles]) -> tuple[dict, list[AnalysisInput], str]:
    batch, documents, digest = load_batch(batch_dir)
    by_id = {r.document_id: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {d.document_id for d in documents}:
        raise ValueError("analyses must cover the 10 batch documents exactly")
    inputs = []
    for document in documents:
        row = by_id[document.document_id]
        composition = Path(row.composition_path).read_bytes()
        discovery = Path(row.discovery_path).read_bytes()
        inputs.append(AnalysisInput(document, CompositionProposal.model_validate_json(composition),
                                    DiscoveryProposal.model_validate_json(discovery), sha(composition), sha(discovery)))
    return batch, inputs, digest


def collect_observations(request: AnalysisBatchRequest, output: Path) -> list[str]:
    _, inputs, digest = _load_analyses(Path(request.prepared_batch), request.documents)
    errors = [f"{i.document.document_id}:{e}" for i in inputs for e in validate_discovery(
        i.discovery, i.composition, i.document, composition_sha256=i.composition_sha256)]
    base = _json(Path(request.approved_base_path)) if request.approved_base_path else None
    if base is not None and base.get("status") != "offline_approved":
        raise ValueError("base dictionary must be offline approved")
    with _new_directory(output):
        write_json(output / "context.json", {
            "instructions": CONSOLIDATION_INSTRUCTIONS, "source_bundle_sha256": digest,
            "prepared_batch": str(Path(request.prepared_batch).resolve()),
            "documents": [{"composition": i.composition.model_dump(), "discovery": i.discovery.model_dump()}
                          for i in inputs],
            "base_catalogue": base["catalogue"] if base else None,
            "base_dictionary_sha256": sha(Path(request.approved_base_path).read_bytes()) if base else None,
            "consolidation_schema": ConsolidationProposal.model_json_schema(),
            "blocking_issues": errors,
        })
    return errors


def _read_local(directory: Path, name: str, expected_sha256: str) -> bytes:
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("draft input leaves its bundle")
    raw = path.read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError(f"draft input hash mismatch: {name}")
    return raw


def _recompute_draft(directory: Path) -> tuple[dict, str, FinalReview | None, str | None]:
    sources = _json(directory / "draft_sources.json")
    batch, _, digest = load_batch(Path(sources["prepared_batch"]))
    if digest != sources["source_bundle_sha256"]:
        raise ValueError("prepared batch changed after draft creation")
    for name, checksum in sources["files"].items():
        _read_local(directory, name, checksum)
    rows = [AnalysisFiles(document_id=e["document_id"],
                           composition_path=str(directory / e["composition_file"]),
                           discovery_path=str(directory / e["discovery_file"])) for e in sources["analyses"]]
    _, inputs, _ = _load_analyses(Path(sources["prepared_batch"]), rows)
    proposal = ConsolidationProposal.model_validate_json((directory / "consolidation.json").read_bytes())
    base = _json(directory / "base.json") if "base.json" in sources["files"] else None
    previous = _json(directory / "previous_draft.json") if "previous_draft.json" in sources["files"] else None
    previous_review_raw = (directory / "previous_review.json").read_bytes() if previous is not None else None
    expected = build_dictionary_draft(
        inputs, proposal, batch_id=batch["batch_id"], source_bundle_sha256=digest,
        source_notices=[e["notice_number"] for e in batch["documents"]],
        source_hashes=[e["source_sha256"] for e in batch["documents"]], base=base,
        base_sha256=sources["files"].get("base.json"), previous=previous,
        previous_sha256=sources["files"].get("previous_draft.json"),
    )
    raw = (directory / "draft.json").read_bytes()
    if json.loads(raw) != expected:
        raise ValueError("draft does not match recomputed source inputs")
    return expected, sha(raw), (FinalReview.model_validate_json(previous_review_raw) if previous_review_raw else None), (
        sha(previous_review_raw) if previous_review_raw else None)


def build_draft_bundle(request: AnalysisBatchRequest, proposal_path: Path, output: Path,
                       *, previous_bundle: Path | None = None, previous_review_path: Path | None = None) -> dict:
    batch, inputs, digest = _load_analyses(Path(request.prepared_batch), request.documents)
    if bool(previous_bundle) != bool(previous_review_path):
        raise ValueError("previous bundle and review must be provided together")
    files = {"consolidation.json": proposal_path.read_bytes()}
    if request.approved_base_path:
        files["base.json"] = Path(request.approved_base_path).read_bytes()
    if previous_bundle is not None:
        _recompute_draft(previous_bundle)
        files["previous_draft.json"] = (previous_bundle / "draft.json").read_bytes()
        files["previous_review.json"] = previous_review_path.read_bytes()
        previous_review = FinalReview.model_validate_json(files["previous_review.json"])
        if previous_review.draft_sha256 != sha(files["previous_draft.json"]):
            raise ValueError("previous review does not match previous draft")
    rows = {r.document_id: r for r in request.documents}
    analyses = []
    for i in inputs:
        doc_id = i.document.document_id
        c, d = f"composition_{doc_id}.json", f"discovery_{doc_id}.json"
        files[c] = Path(rows[doc_id].composition_path).read_bytes()
        files[d] = Path(rows[doc_id].discovery_path).read_bytes()
        if sha(files[c]) != i.composition_sha256 or sha(files[d]) != i.discovery_sha256:
            raise ValueError("analysis changed during build")
        analyses.append({"document_id": doc_id, "composition_file": c, "discovery_file": d})
    proposal = ConsolidationProposal.model_validate_json(files["consolidation.json"])
    draft = build_dictionary_draft(
        inputs, proposal, batch_id=batch["batch_id"], source_bundle_sha256=digest,
        source_notices=[e["notice_number"] for e in batch["documents"]],
        source_hashes=[e["source_sha256"] for e in batch["documents"]],
        base=json.loads(files["base.json"]) if "base.json" in files else None,
        base_sha256=sha(files["base.json"]) if "base.json" in files else None,
        previous=json.loads(files["previous_draft.json"]) if previous_bundle else None,
        previous_sha256=sha(files["previous_draft.json"]) if previous_bundle else None,
    )
    with _new_directory(output):
        for name, raw in files.items():
            (output / name).write_bytes(raw)
        write_json(output / "draft_sources.json", {"prepared_batch": str(Path(request.prepared_batch).resolve()),
            "source_bundle_sha256": digest, "analyses": analyses, "files": {k: sha(v) for k, v in files.items()}})
        write_json(output / "draft.json", draft)
        write_json(output / "requirements.json", {"observations": draft["requirements"], "groups": draft["condition_groups"]})
        review_ids = set(draft["required_review_ids"])
        if previous_bundle:
            review_ids.update(f.review_id for f in FinalReview.model_validate_json(files["previous_review.json"]).findings)
        write_json(output / "review_context.json", {"instructions": FINAL_REVIEW_INSTRUCTIONS,
            "prepared_batch": str(Path(request.prepared_batch).resolve()),
            "draft_sha256": sha((output / "draft.json").read_bytes()), "source_bundle_sha256": digest,
            "previous_review_sha256": sha(files["previous_review.json"]) if previous_bundle else None,
            "required_review_ids": sorted(review_ids), "blocking_issues": draft["blocking_issues"],
            "review_schema": FinalReview.model_json_schema()})
        with (output / "attributes.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["속성ID", "속성명", "의미", "구성요소유형", "단위", "집계", "구성상태", "측정기준"])
            for a in draft["catalogue"]["attributes"]:
                writer.writerow([a["attribute_id"], a["name"], a["meaning"]["definition"],
                    ",".join(a["component_type_ids"]), a["canonical_unit"], a["meaning"]["aggregation"],
                    a["meaning"]["configuration"], a["meaning"]["measurement_basis"]])
    return draft


def check_draft_bundle(directory: Path, review_path: Path) -> tuple[dict, dict, FinalReview, FinalReview | None, str | None]:
    draft, checksum, previous, previous_hash = _recompute_draft(directory)
    raw = review_path.read_bytes()
    review = FinalReview.model_validate_json(raw)
    result = validate_final_review(draft, review, draft_sha256=checksum,
                                   previous_review=previous, previous_review_sha256=previous_hash)
    result["review_sha256"] = sha(raw)
    return draft, result, review, previous, previous_hash


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ["prepare", "collect", "build"]:
        child = commands.add_parser(command)
        child.add_argument("--request", type=Path, required=True)
        child.add_argument("--output-dir", type=Path, required=True)
        if command == "build":
            child.add_argument("--proposal", type=Path, required=True)
            child.add_argument("--previous-draft-dir", type=Path)
            child.add_argument("--previous-review", type=Path)
    for command in ["check", "approve"]:
        child = commands.add_parser(command)
        child.add_argument("--draft-dir", type=Path, required=True)
        child.add_argument("--review", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
        if command == "approve":
            child.add_argument("--reviewer", required=True)
            child.add_argument("--authorization-note", required=True)
    args = parser.parse_args()
    try:
        errors = []
        if args.command == "prepare":
            prepare_batch(BatchRequest.model_validate_json(args.request.read_bytes()), args.output_dir)
        elif args.command == "collect":
            errors = collect_observations(AnalysisBatchRequest.model_validate_json(args.request.read_bytes()), args.output_dir)
        elif args.command == "build":
            draft = build_draft_bundle(AnalysisBatchRequest.model_validate_json(args.request.read_bytes()), args.proposal,
                                      args.output_dir, previous_bundle=args.previous_draft_dir,
                                      previous_review_path=args.previous_review)
            errors = draft["blocking_issues"]
        else:
            draft, result, review, previous, previous_hash = check_draft_bundle(args.draft_dir, args.review)
            if args.command == "check":
                write_json(args.output, result)
                errors = result["blocking_issues"]
            else:
                artifact = approve_offline_dictionary(draft, review, draft_sha256=result["draft_sha256"],
                    review_sha256=result["review_sha256"], reviewer_label=args.reviewer,
                    authorization_note=args.authorization_note, previous_review=previous,
                    previous_review_sha256=previous_hash)
                write_json(args.output, artifact)
        print(json.dumps({"stage": args.command, "blocking_issue_count": len(errors)}))
        if errors:
            parser.exit(2, "dictionary bootstrap requires correction; see saved issues\n")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"dictionary bootstrap failed: {error}\n")


if __name__ == "__main__":
    main()
