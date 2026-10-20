"""Offline composition review over saved parses; semantic proposals are authored by Codex.

Primary units are a review projection, not a claim about physical BOM depth.
No parsing, model API, dictionary approval, database or workflow integration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .document_evidence import (
    EvidenceQuote, ParsedEvidenceDocument, build_document_evidence, comparable_text,
    validate_evidence,
)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Record):
    target_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: Literal["root", "primary", "detail", "external", "test_object", "service", "document_group"]
    nature: Literal["equipment", "space", "system", "software", "bundle", "other"]
    parent_id: str | None
    relation: Literal["ROOT", "REVIEW_UNIT_OF", "DETAIL_OF", "REFERENCE_ONLY", "SERVICE_FOR", "GROUPS"]
    relationship_basis: Literal["explicit", "interpreted"]
    reason: str = Field(min_length=1)
    node_ids: list[str] = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class RequirementExcerpt(Record):
    """Source-preserving examples, not normalized or exhaustive requirements."""
    observation_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    property_raw: str = Field(min_length=1)
    value_text: str = Field(min_length=1)
    modality: Literal["required", "recommended", "uncertain"]
    evidence: list[EvidenceQuote] = Field(min_length=1)
    notes: str = Field(min_length=1)


class CompositionProposal(Record):
    schema_version: Literal["composition_proposal_v1"] = "composition_proposal_v1"
    document_id: str = Field(min_length=1)
    native_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_method: Literal["codex_interactive_reading"]
    reference_seen: bool
    revision: str = Field(min_length=1)
    targets: list[Target] = Field(min_length=1)
    requirement_excerpts: list[RequirementExcerpt] = Field(default_factory=list)
    limitations: list[str] = Field(min_length=1)


ANALYSIS_INSTRUCTIONS = """분석과 설명은 한국어로 작성한다.
문서 전체를 읽고 공급 목록, 기술 규격, 부속품, 검수 조건을 함께 확인한다.
문서 제목의 번호나 들여쓰기를 물리 구성 계층으로 복사하지 않는다.
root는 구매 완성품이다. primary는 사용자가 확인할 주요 규격 단위다.
장치뿐 아니라 별도 규격이 있는 공간, 소프트웨어, 부속품 묶음도 primary일 수 있다.
명시 구성 목록을 우선하되 본문의 별도 규격 단위와 대조한다.
detail은 주요 단위 내부의 부품·장치다. 모든 세부 장치를 primary로 승격하지 않는다.
같은 이름이어도 소유 대상·역할이 다르면 분리한다. 다른 표현의 통합은 근거를 쓴다.
외부 제공품, 시험 대상, 서비스, 단순 문서 그룹을 납품 구성 목록과 구분한다.
주요 단위 묶기와 하위 관계가 해석이면 interpreted로 기록한다.
원문 노드와 인용을 보존하고 비연속 구간도 같은 대상에 연결한다.
하위 장치의 수치를 상위 전체 성능으로 옮기지 않는다.
번호 반복, 수량 불명, 권장/필수 충돌, 이미지 미확인은 해결한 것처럼 쓰지 않는다.
출력은 CompositionProposal JSON이다. 기대 구성품 수나 정답 목록은 입력하지 않는다.
requirement_excerpts는 대표 규격 검토용이며 전체 속성 추출·표준 매핑을 뜻하지 않는다.
"""


def validate_composition(proposal: CompositionProposal, document: ParsedEvidenceDocument) -> dict:
    if (proposal.document_id, proposal.native_sha256) != (document.document_id, document.native_sha256):
        raise ValueError("document identity/hash mismatch")
    errors: list[str] = []
    targets = {t.target_id: t for t in proposal.targets}
    nodes = {n.node_id: n for n in document.nodes}
    if len(targets) != len(proposal.targets):
        errors.append("duplicate_target_id")
    roots = [t for t in proposal.targets if t.role == "root"]
    if not roots:
        errors.append("missing_root")
    allowed = {
        "root": ("ROOT", None), "primary": ("REVIEW_UNIT_OF", {"root"}),
        "detail": ("DETAIL_OF", {"primary", "detail"}),
        "external": ("REFERENCE_ONLY", {"root", "primary", "detail"}),
        "test_object": ("REFERENCE_ONLY", {"root", "primary", "detail"}),
        "service": ("SERVICE_FOR", {"root", "primary", "detail"}),
        "document_group": ("GROUPS", {"root", "primary", "detail"}),
    }
    covered: set[str] = set()
    for target in proposal.targets:
        prefix = target.target_id
        errors.extend(f"{prefix}:{e}" for e in validate_evidence(target.evidence, [document]))
        if len(set(target.node_ids)) != len(target.node_ids):
            errors.append(f"{prefix}:duplicate_node")
        if not set(target.node_ids) <= nodes.keys():
            errors.append(f"{prefix}:unknown_node")
        if any(e.node_id not in target.node_ids for e in target.evidence):
            errors.append(f"{prefix}:evidence_outside_scope")
        expected_relation, parent_roles = allowed[target.role]
        if target.relation != expected_relation:
            errors.append(f"{prefix}:role_relation_mismatch")
        parent = targets.get(target.parent_id)
        if parent_roles is None:
            if target.parent_id is not None:
                errors.append(f"{prefix}:root_has_parent")
        elif parent is None or parent.role not in parent_roles:
            errors.append(f"{prefix}:invalid_parent")
        seen: set[str] = set()
        current = target
        while current:
            if current.target_id in seen:
                errors.append(f"{prefix}:cycle")
                break
            seen.add(current.target_id)
            current = targets.get(current.parent_id)
        covered.update(target.node_ids)
    observations = proposal.requirement_excerpts
    if len({o.observation_id for o in observations}) != len(observations):
        errors.append("duplicate_observation_id")
    for observation in observations:
        prefix = observation.observation_id
        errors.extend(f"{prefix}:{e}" for e in validate_evidence(observation.evidence, [document]))
        owner = targets.get(observation.owner_id)
        if owner is None or owner.role not in {"root", "primary", "detail"}:
            errors.append(f"{prefix}:invalid_requirement_owner")
        elif any(e.node_id not in owner.node_ids for e in observation.evidence):
            errors.append(f"{prefix}:requirement_outside_owner_scope")
        if not comparable_text(observation.value_text) or not any(comparable_text(observation.value_text) in comparable_text(e.quote)
                   for e in observation.evidence):
            errors.append(f"{prefix}:value_not_in_quote")
    primary = [t for t in proposal.targets if t.role == "primary"]
    return {
        "schema_version": "composition_validation_v1",
        "document_id": document.document_id,
        "structural_status": "failed" if errors else "passed",
        "errors": sorted(set(errors)),
        "primary_units": [{"target_id": t.target_id, "name": t.name} for t in primary],
        "unassigned_text_node_ids": [n.node_id for n in document.nodes
                                     if n.text.strip() and n.kind != "image" and n.node_id not in covered],
        "unassessed_native_refs": list(document.unreadable_refs),
        "parser_warnings": list(document.warnings),
        "semantic_review_status": "pending",
        "automatic_compliance_ready": False,
    }


def comparison_name(name: str) -> str:
    """Formatting equivalence only; no invented synonyms or semantic matching."""
    # Retain model/type parentheses. Only the fixture's explicit quantity and
    # test-section annotations are ignored for this list-level comparison.
    return comparable_text(re.sub(
        r"\((?:\d+\s*(?:대|set|EA|개)|동적주행성능시험|정적상태진단시험)\)",
        "", name, flags=re.IGNORECASE,
    ))


def evaluate_components(proposal: CompositionProposal, expected_names: list[str]) -> dict:
    """Exact normalized one-to-one review-list comparison, independent of validation."""
    predicted = [t.name for t in proposal.targets if t.role == "primary"]
    remaining = list(expected_names)
    matches = []
    unexpected = []
    for name in predicted:
        match = next((i for i, expected in enumerate(remaining)
                      if comparison_name(name) == comparison_name(expected)), None)
        if match is None:
            unexpected.append(name)
        else:
            matches.append({"predicted": name, "reference": remaining.pop(match)})
    tp, fp, fn = len(matches), len(unexpected), len(remaining)
    return {"document_id": proposal.document_id, "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "matches": matches, "unexpected": unexpected, "missing": remaining,
            "evaluation_scope": "development_reference_agreement" if proposal.reference_seen else "reference_agreement",
            "semantic_accuracy_measured": False}


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_document(native_path: Path, document_id: str) -> ParsedEvidenceDocument:
    raw = native_path.read_bytes()
    return build_document_evidence(json.loads(raw), document_id=document_id,
                                   parse_run_id="saved_native", native_sha256=hashlib.sha256(raw).hexdigest())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--native", type=Path, required=True)
    prepare.add_argument("--document-id", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--native", type=Path, required=True)
    validate.add_argument("--proposal", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--proposal", type=Path, required=True)
    evaluate.add_argument("--reference", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            document = load_document(args.native, args.document_id)
            write_json(args.output, {"instructions": ANALYSIS_INSTRUCTIONS, "source": document.context(),
                                     "output_schema": CompositionProposal.model_json_schema()})
        else:
            proposal = CompositionProposal.model_validate_json(args.proposal.read_bytes())
            if args.command == "validate":
                result = validate_composition(proposal, load_document(args.native, proposal.document_id))
            else:
                reference = json.loads(args.reference.read_bytes())
                expected = next(d["components"] for d in reference["documents"]
                                if d["document_id"] == proposal.document_id)
                result = evaluate_components(proposal, expected)
                result["reference_sha256"] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
            result["proposal_sha256"] = hashlib.sha256(args.proposal.read_bytes()).hexdigest()
            write_json(args.output, result)
            if result.get("errors"):
                parser.exit(2, "composition structural validation failed; see output\n")
    except (ValueError, OSError, StopIteration) as error:
        parser.exit(2, f"composition review failed: {error}\n")


if __name__ == "__main__":
    main()
