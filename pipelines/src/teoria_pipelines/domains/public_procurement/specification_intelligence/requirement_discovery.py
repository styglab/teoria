"""Source-first property observations; independent of any standard dictionary."""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .composition_analysis import CompositionProposal, validate_composition
from .document_evidence import EvidenceQuote, ParsedEvidenceDocument, comparable_text, validate_evidence


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyMeaning(Record):
    definition: str = Field(min_length=1)
    property_kind: str = Field(min_length=1)
    data_type: Literal["number", "text", "boolean", "formula"]
    dimension: str = Field(min_length=1)
    aggregation: Literal["per_instance", "total", "per_slot", "not_applicable", "unknown"]
    configuration: Literal["installed", "supported", "existing", "not_applicable", "unknown"]
    measurement_basis: str = Field(min_length=1)

    def signature(self) -> tuple:
        # A necessary compatibility check, not proof of semantic equivalence.
        # property_kind and definition are open semantic labels, not existing IDs.
        # Their equivalence is reviewed; literal equality would defeat bootstrap.
        return (self.data_type, self.dimension, self.aggregation,
                self.configuration, self.measurement_basis)


class PropertyObservation(Record):
    observation_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["property", "software_requirement", "operational_requirement"] = "property"
    owner_id: str = Field(min_length=1)
    raw_attribute: str | None
    raw_text: str = Field(min_length=1)
    meaning: PropertyMeaning
    operator: Literal["EQ", "GE", "GT", "LE", "LT", "RANGE", "IN", "REQUIRED", "PROHIBITED",
                      "EQUIVALENT_OR_BETTER", "QUALITATIVE", "UNKNOWN"]
    operator_text: str | None = None
    value_text: str = Field(min_length=1)
    unit_raw: str | None
    modality: Literal["required", "recommended", "uncertain"]
    qualifiers: list[str] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class ConditionGroup(Record):
    group_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    logic: Literal["AND", "OR", "IF"]
    members: list[str] = Field(min_length=1)
    antecedents: list[str] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(min_length=1)
    explanation: str = Field(min_length=1)


class NodeCoverage(Record):
    node_id: str
    decision: Literal["observed", "partially_observed", "non_property", "deferred"]
    observation_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class UnreadableCoverage(Record):
    native_ref: str
    decision: Literal["non_property", "deferred"]
    reason: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class DiscoveryProposal(Record):
    schema_version: Literal["requirement_discovery_v1"] = "requirement_discovery_v1"
    document_id: str
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    composition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_method: Literal["codex_interactive_reading"]
    revision: str = Field(min_length=1)
    observations: list[PropertyObservation]
    groups: list[ConditionGroup] = Field(default_factory=list)
    coverage: list[NodeCoverage]
    unreadable_coverage: list[UnreadableCoverage] = Field(default_factory=list)
    limitations: list[str] = Field(min_length=1)


DISCOVERY_INSTRUCTIONS = """기존 사전이나 표준 속성 ID 없이 원문에서 요구조건을 발견한다.
CompositionProposal의 주요 단위와 하위 대상·원문 범위를 재사용한다.
필요한 소유 대상이 빠졌으면 먼저 구성 제안을 수정하고 다시 검사한다.
원문 표현과 속성 의미 후보를 동시에 저장한다. raw_attribute가 원문에 없으면 null이다.
속성 의미는 장착/지원/기보유, 개별/전체/슬롯당, 기본/부스트 등 측정 기준을 구별한다.
value_text와 unit_raw는 원문 표기를 보존하며 수치 합산·단위 변환·불명확한 약어 확정을 하지 않는다.
문장에 여러 조건이 있으면 원자 관찰로 나누고 AND/OR/IF 관계와 시험 조건을 보존한다.
모든 텍스트 노드에 관찰/속성 외 조건/보류를 기록한다. 한 노드의 모든 조건을 읽고 확인한다.
이미지·파싱 손실을 조용히 제외하지 않는다. 미확인 영역은 deferred로 남긴다.
속성 외 납품·교육·보증 조건도 non_property 사유로 보존하며 삭제한 것으로 취급하지 않는다.
출력은 DiscoveryProposal이다. 의미 판단은 제안이며 구조 검사 통과는 승인이나 완전성 보장이 아니다.
"""


def validate_discovery(proposal: DiscoveryProposal, composition: CompositionProposal,
                       document: ParsedEvidenceDocument, *, composition_sha256: str) -> list[str]:
    if (proposal.document_id, proposal.native_sha256, proposal.composition_sha256) != (
            document.document_id, document.native_sha256, composition_sha256):
        raise ValueError("discovery input identity/hash mismatch")
    errors = list(validate_composition(composition, document)["errors"])
    owners = {t.target_id: t for t in composition.targets}
    observations = {o.observation_id: o for o in proposal.observations}
    if len(observations) != len(proposal.observations):
        errors.append("duplicate_observation_id")
    for o in proposal.observations:
        prefix = o.observation_id
        errors.extend(f"{prefix}:{e}" for e in validate_evidence(o.evidence, [document]))
        owner = owners.get(o.owner_id)
        if owner is None or owner.role not in {"root", "primary", "detail"}:
            errors.append(f"{prefix}:invalid_owner")
        elif any(e.node_id not in owner.node_ids for e in o.evidence):
            errors.append(f"{prefix}:evidence_outside_owner")
        for field, text in [("raw_text", o.raw_text), ("value", o.value_text),
                            ("raw_attribute", o.raw_attribute), ("unit", o.unit_raw),
                            ("operator", o.operator_text), *[("qualifier", q) for q in o.qualifiers]]:
            if text is not None and (not comparable_text(text) or not any(
                    comparable_text(text) in comparable_text(e.quote) for e in o.evidence)):
                errors.append(f"{prefix}:{field}_not_in_evidence")
        value = unicodedata.normalize("NFKC", o.value_text).strip()
        # Retain separators: removing whitespace joins DDR5 + 512GB into DDR5512GB.
        # Model names and other text containing digits use the verbatim check above.
        if re.fullmatch(r"[+\-−]?\d+(?:[.,]\d+)*", value) and not any(re.search(
                r"(?<![\d.,+\-−])" + re.escape(value) + r"(?![\d.,])",
                unicodedata.normalize("NFKC", e.quote)) for e in o.evidence):
            errors.append(f"{prefix}:numeric_value_not_exact_in_evidence")
        operator_tokens = {"이상": "GE", ">=": "GE", "≥": "GE", "이하": "LE", "<=": "LE", "≤": "LE",
                           "초과": "GT", ">": "GT", "미만": "LT", "<": "LT", "=": "EQ"}
        if o.operator_text in operator_tokens and operator_tokens[o.operator_text] != o.operator:
            errors.append(f"{prefix}:operator_evidence_mismatch")
        if o.operator == "UNKNOWN" or o.modality == "uncertain" or "unknown" in o.meaning.signature():
            errors.append(f"{prefix}:unresolved_interpretation")

    groups = {g.group_id: g for g in proposal.groups}
    if len(groups) != len(proposal.groups) or groups.keys() & observations.keys():
        errors.append("duplicate_condition_id")
    for group in proposal.groups:
        errors.extend(f"{group.group_id}:{e}" for e in validate_evidence(group.evidence, [document]))
        refs = group.members + group.antecedents
        if len(set(refs)) != len(refs) or any(r not in groups and r not in observations for r in refs):
            errors.append(f"{group.group_id}:invalid_group_reference")
        if ((group.logic == "IF") != bool(group.antecedents)
                or (group.logic != "IF" and len(group.members) < 2)):
            errors.append(f"{group.group_id}:invalid_logic")
    def visit(key: str, chain: set[str]) -> None:
        if key in chain:
            errors.append("condition_cycle")
        elif key in groups:
            group = groups[key]
            for child in group.members + group.antecedents:
                visit(child, chain | {key})
    for key in groups:
        visit(key, set())

    nodes = {n.node_id for n in document.nodes if n.text.strip() and n.kind != "image"}
    covered = {c.node_id for c in proposal.coverage}
    if len(covered) != len(proposal.coverage) or covered != nodes:
        errors.append("incomplete_or_duplicate_node_coverage")
    observed_pairs = {(e.node_id, o.observation_id) for o in proposal.observations for e in o.evidence}
    coverage_pairs = set()
    for c in proposal.coverage:
        if c.decision in {"deferred", "partially_observed"}:
            errors.append(f"{c.node_id}:deferred_text")
        if (c.decision in {"observed", "partially_observed"}) != bool(c.observation_ids):
            errors.append(f"{c.node_id}:coverage_observation_mismatch")
        if len(set(c.observation_ids)) != len(c.observation_ids):
            errors.append(f"{c.node_id}:duplicate_coverage_reference")
        coverage_pairs.update((c.node_id, key) for key in c.observation_ids)
    if coverage_pairs != observed_pairs:
        errors.append("coverage_evidence_mismatch")
    unreadable = {c.native_ref for c in proposal.unreadable_coverage}
    if len(unreadable) != len(proposal.unreadable_coverage) or unreadable != set(document.unreadable_refs):
        errors.append("incomplete_unreadable_coverage")
    for c in proposal.unreadable_coverage:
        errors.extend(validate_evidence(c.evidence, [document]))
        if c.decision == "deferred":
            errors.append(f"{c.native_ref}:deferred_unreadable")
    return sorted(set(errors))
