"""Offline frozen-dictionary reuse and source-anchored Semantic IR evaluation.

This experiment consumes suggestions; it neither edits nor publishes a dictionary.
Evaluation references are separate from inference inputs and never repair predictions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from . import semantic_batch as batch
from .codex_runner import CodexRunner
from .document_evidence import EvidenceQuote, comparable_text, validate_evidence
from .semantic_ir import Definition, DocumentAnalysis, Record, canonical_ids, observations, require, unique, validate_analysis


class ReuseDecision(Record):
    observation_ref: str
    decision: Literal["reuse", "new_candidate", "applicability_gap", "ambiguous", "exclude"]
    concept_id: str | None
    reason: str = Field(min_length=1)


class ReuseProposal(Record):
    decisions: list[ReuseDecision]
    issues: list[str]


REUSE = batch.BASE + """기존 의미 정의를 변경하지 않고 한국어로 문서 관찰을 고정 사전에 연결한다.
각 entity/requirement/relation의 observation_ref=document_id/관찰ID에 정확히 한 결정을 기록한다.
decision은 reuse/new_candidate/applicability_gap/ambiguous/exclude다.
reuse는 종류·측정 의미·차원·적용 대상 모두 일치해야 한다. 이름 유사성만으로 연결하지 않는다.
같은 개념을 재사용해도 문서별 개체는 합치지 않는다. 값·문맥 역할만 다르면 신규 개념이 아니다.
applicability_gap은 의미·차원은 맞지만 사전의 적용 대상에 해당 엔티티가 없는 속성이다.
reuse와 applicability_gap만 기존 concept_id를 갖고 나머지는 null이다.
새 측정 의미·개념만 new_candidate로 제안한다. 불명확한 기본/부스트 클럭, 귀속 불명,
기존 개념인지 새 의미인지 불명확한 경우 ambiguous로 남긴다. 기존 정의나 ID를 생성하지 않는다.
functional/service/delivery/other 조건은 그래프에 유지하되 exclude한다.
CPU/GPU 코어, SSD 읽기 속도/네트워크 전송률, 총량/모듈당, 장착/지원을 구분한다.
전체 후보 사전을 제공한다. 판단 이유를 남기고 출력은 ReuseProposal 스키마를 따른다.
"""


def definitions(value: dict) -> list[Definition]:
    result = [Definition.model_validate(row) for row in value["definitions"]]
    unique([row.concept_id for row in result], "dictionary concept")
    lookup = {row.concept_id: row for row in result}
    for row in result:
        require(all(key in lookup and lookup[key].kind == "entity"
                    for key in row.applicable_entity_concept_ids), "invalid dictionary applicability")
    return result


def validate_reuse(proposal: ReuseProposal, graph: DocumentAnalysis, dictionary: list[Definition]):
    source = observations([graph])
    unique([row.observation_ref for row in proposal.decisions], "reuse observation")
    decisions = {row.observation_ref: row for row in proposal.decisions}
    require(decisions.keys() == source.keys(), "reuse decisions must cover every observation")
    lookup = {row.concept_id: row for row in dictionary}
    canonical = canonical_ids(graph)
    for alias, target in canonical.items():
        left, right = decisions[f"{graph.document_id}/{alias}"], decisions[f"{graph.document_id}/{target}"]
        require((left.decision, left.concept_id) == (right.decision, right.concept_id),
                "same target observations have inconsistent reuse decisions")
    for decision in proposal.decisions:
        kind, row = source[decision.observation_ref]
        if decision.decision not in {"reuse", "applicability_gap"}:
            require(decision.concept_id is None, "unresolved decision cannot assign concept")
            require(decision.decision == "exclude" or kind != "property" or row.kind == "property",
                    "non-property requirements must be excluded")
            continue
        definition = lookup.get(decision.concept_id)
        require(definition is not None and definition.kind == kind, "reuse concept kind mismatch")
        if kind == "property":
            require(row.kind == "property", "non-property requirement cannot reuse property")
            require(row.scope != "unknown", "unresolved subject scope must remain ambiguous")
            require(definition.dimension == row.dimension, "reuse property dimension mismatch")
            subject = decisions.get(f"{graph.document_id}/{row.subject_id}")
            require(subject is not None and subject.decision == "reuse", "unresolved subject must remain ambiguous")
            applicable = subject.concept_id in definition.applicable_entity_concept_ids
            require(applicable == (decision.decision == "reuse"), "reuse applicability mismatch")
        else:
            require(decision.decision != "applicability_gap", "only properties have applicability gaps")
        if kind == "relation":
            require(definition.predicate == row.predicate, "reuse relation predicate mismatch")


async def run(root: Path, dictionary_path: Path, output: Path, runner: CodexRunner) -> dict:
    """Run item identification, scoped extraction, resolution and validation before dictionary reuse."""
    require(not output.exists(), "use a new evaluation revision directory")
    batch.verify(root)
    dictionary_bytes = dictionary_path.read_bytes()
    dictionary = definitions(json.loads(dictionary_bytes))
    output.mkdir(parents=True)
    (output / "dictionary.json").write_bytes(dictionary_bytes)
    batch.save(output / "inputs.json", {
        "batch": str(root.resolve()), "batch_freeze_sha256": batch.digest(root / "freeze.json"),
        "dictionary_sha256": batch.digest(output / "dictionary.json"),
        "status": "suggestion", "published": False, "human_reviewed": False,
    })
    timings = []
    started = time.monotonic()
    stage = "identify"
    try:
        for stage in batch.DOCUMENT_STAGES:
            tick = time.monotonic()
            cached = all((root / stage / f"{d.document_id}.json").exists() for d in batch.verify(root).documents)
            await batch.run_stage(root, stage, runner)
            timings.append({"stage": stage, "seconds": round(time.monotonic() - tick, 3), "cached": cached})
        graphs = batch.analyses(root)
        for stage in batch.DOCUMENT_STAGES:
            for graph in graphs:
                batch.verify_accepted(root, stage, graph.document_id)
        checks = [batch.accepted(root, "validate", graph.document_id) for graph in graphs]
        require(not any(f["severity"] == "error" for check in checks for f in check["findings"]),
                "source validation errors block dictionary reuse")
        stage = "reuse"
        tick = time.monotonic()
        proposals = []
        for graph in graphs:
            payload = {"graph": graph.model_dump(), "definitions": [d.model_dump() for d in dictionary],
                       "schema": ReuseProposal.model_json_schema()}
            cache = output / "inference" / f"{graph.document_id}.json"
            raw = await runner.generate(REUSE, payload, cache)
            for attempt in range(2):
                try:
                    proposal = ReuseProposal.model_validate(raw)
                    validate_reuse(proposal, graph, dictionary)
                    break
                except ValueError as error:
                    if attempt:
                        raise
                    raw = await runner.generate(REUSE, {**payload, "proposal": raw, "validation_error": str(error)},
                                                cache.with_name(f"{graph.document_id}_repair.json"))
            proposals.extend(d.model_dump() for d in proposal.decisions)
        timings.append({"stage": stage, "seconds": round(time.monotonic() - tick, 3), "cached": False})
        require(dictionary_path.read_bytes() == dictionary_bytes, "source dictionary changed during run")
        require((output / "dictionary.json").read_bytes() == dictionary_bytes, "dictionary snapshot changed")
        batch.verify(root)
        batch.save(output / "document_graphs.json", [g.model_dump() for g in graphs])
        batch.save(output / "mappings.json", proposals)
        counts = {key: sum(d["decision"] == key for d in proposals)
                  for key in ("reuse", "new_candidate", "applicability_gap", "ambiguous", "exclude")}
        result = {"status": "needs_review", "execution": "completed", "documents": len(graphs),
                  "decisions": counts, "dictionary_changed": False, "human_reviewed": False,
                  "published": False, "semantic_accuracy_measured": False, "timings": timings,
                  "seconds": round(time.monotonic() - started, 3)}
        batch.save(output / "summary.json", result)
        batch.save(output / "freeze.json", {str(p.relative_to(output)): batch.digest(p)
                   for p in output.rglob("*") if p.is_file()})
        return result
    except Exception as error:
        batch.save(output / "failure.json", {"execution": "failed", "stage": stage,
                   "error": f"{type(error).__name__}: {error}", "timings": timings,
                   "seconds": round(time.monotonic() - started, 3), "manual_fallback": False})
        raise


class SemanticCheck(Record):
    check_id: str
    kind: Literal["entity", "property", "relation"]
    evidence: EvidenceQuote
    expected: dict = Field(min_length=1)
    forbidden: bool = False


class References(Record):
    checks: list[SemanticCheck] = Field(min_length=1)
    label_status: Literal["silver", "human_reviewed"]
    scope: Literal["selected_checks"] = "selected_checks"


def score(references: References, graphs: list[DocumentAnalysis], decisions: list[ReuseDecision], documents: list) -> dict:
    """One-to-one positive checks and explicit forbidden merges; no full recall claim."""
    unique([c.check_id for c in references.checks], "reference check")
    unique([g.document_id for g in graphs], "evaluated document")
    document_lookup = {d.document_id: d for d in documents}
    for graph in graphs:
        require(graph.document_id in document_lookup, "unknown evaluated document")
        validate_analysis(graph, document_lookup[graph.document_id])
    mapping = {d.observation_ref: d for d in decisions}
    source = observations(graphs)
    require(mapping.keys() == source.keys() and len(mapping) == len(decisions), "incomplete evaluation mappings")
    features = {}
    for ref, (kind, row) in source.items():
        document_id = ref.split("/", 1)[0]
        fields = row.model_dump()
        fields.update(concept_id=mapping[ref].concept_id, decision=mapping[ref].decision)
        for endpoint in ("subject", "object"):
            target = mapping.get(f"{document_id}/{getattr(row, endpoint + '_id', None)}")
            fields[endpoint + "_concept_id"] = target.concept_id if target else None
        if kind == "property":
            fields["value_unit"] = comparable_text(row.value_text + (row.unit_raw or ""))
            fields.update({"aggregation": row.qualifiers.aggregation, "configuration": row.qualifiers.configuration})
        features[ref] = fields
    allowed = {"concept_id", "decision", "subject_concept_id", "object_concept_id", "value_unit", "dimension",
               "operator", "aggregation", "configuration", "predicate", "basis", "roles",
               "scope", "item_ids", "owner_item_id", "subject_id", "object_id"}
    candidates, diagnostics = {}, {}
    for check in references.checks:
        require(set(check.expected) <= allowed, "unsupported semantic check field")
        require(not validate_evidence([check.evidence], documents), "reference evidence absent from source")
        anchored = [ref for ref, (kind, row) in source.items() if kind == check.kind and
                    any(e.document_id == check.evidence.document_id and e.node_id == check.evidence.node_id and
                        comparable_text(check.evidence.quote) in comparable_text(e.quote) for e in row.evidence)]
        exact = [ref for ref in anchored if all(features[ref].get(key) == value for key, value in check.expected.items())]
        candidates[check.check_id] = exact
        diagnostics[check.check_id] = [{"observation_ref": ref, "mismatches": {
            key: {"expected": value, "actual": features[ref].get(key)} for key, value in check.expected.items()
            if features[ref].get(key) != value}} for ref in anchored]
    # Maximum bipartite matching prevents two expected observations using one prediction.
    assigned = {}
    def match(key, visited):
        for ref in candidates[key]:
            if ref in visited:
                continue
            visited.add(ref)
            if ref not in assigned or match(assigned[ref], visited):
                assigned[ref] = key
                return True
        return False
    for check in references.checks:
        if not check.forbidden:
            match(check.check_id, set())
    matched = set(assigned.values())
    results = [{"check_id": c.check_id, "kind": c.kind, "forbidden": c.forbidden,
                "passed": not candidates[c.check_id] if c.forbidden else c.check_id in matched,
                "matches": candidates[c.check_id], "diagnostics": diagnostics[c.check_id]} for c in references.checks]
    return {"checks": results, "passed": sum(r["passed"] for r in results), "total": len(results),
            "positive_passed": sum(r["passed"] for r in results if not r["forbidden"]),
            "positive_total": sum(not r["forbidden"] for r in results),
            "forbidden_violations": sum(not r["passed"] for r in results if r["forbidden"]),
            "scope": references.scope, "label_status": references.label_status,
            "full_document_precision_recall_measured": False, "independent_accuracy_measured": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run")
    run_cmd.add_argument("--batch", type=Path, required=True)
    run_cmd.add_argument("--dictionary", type=Path, required=True)
    run_cmd.add_argument("--output-dir", type=Path, required=True)
    run_cmd.add_argument("--timeout", type=int, default=240)
    score_cmd = commands.add_parser("score")
    score_cmd.add_argument("--batch", type=Path, required=True)
    score_cmd.add_argument("--result", type=Path, required=True)
    score_cmd.add_argument("--references", type=Path, required=True)
    score_cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(asyncio.run(run(args.batch, args.dictionary, args.output_dir,
                                        CodexRunner(timeout=args.timeout))), ensure_ascii=False))
    else:
        frozen = batch.load(args.result / "freeze.json")
        for name, expected in frozen.items():
            require(batch.digest(args.result / name) == expected, "evaluation result changed")
        inputs = batch.load(args.result / "inputs.json")
        require(batch.digest(args.batch / "freeze.json") == inputs["batch_freeze_sha256"], "evaluation batch mismatch")
        graphs = [DocumentAnalysis.model_validate(g) for g in batch.load(args.result / "document_graphs.json")]
        decisions = [ReuseDecision.model_validate(d) for d in batch.load(args.result / "mappings.json")]
        result = score(References.model_validate(batch.load(args.references)), graphs, decisions, batch.documents(args.batch))
        result["references_sha256"] = batch.digest(args.references)
        batch.save(args.output, result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit(f"semantic evaluation failed: {error}") from None
