"""Build an offline dictionary draft from source observations and semantic proposals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .composition_analysis import CompositionProposal
from .document_evidence import EvidenceQuote, ParsedEvidenceDocument, comparable_text, validate_evidence
from .requirement_discovery import DiscoveryProposal, PropertyMeaning, Record, validate_discovery


class Alias(Record):
    expression: str = Field(min_length=1)
    context: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class ComponentType(Record):
    type_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    aliases: list[Alias] = Field(default_factory=list)


class AttributeDefinition(Record):
    attribute_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    meaning: PropertyMeaning
    component_type_ids: list[str] = Field(min_length=1)
    canonical_unit: str | None
    accepted_raw_units: list[str]
    aliases: list[Alias] = Field(default_factory=list)


class TypeBinding(Record):
    document_id: str
    target_id: str
    type_id: str
    reason: str = Field(min_length=1)


class MappingDecision(Record):
    observation_ref: str  # document_id/observation_id
    decision: str = Field(pattern=r"^(MAP|HOLD|EXCLUDE)$")
    attribute_id: str | None
    reason: str = Field(min_length=1)


class AliasAddition(Record):
    target_kind: Literal["component_type", "attribute"]
    target_id: str
    alias: Alias


class ConsolidationProposal(Record):
    schema_version: str = Field(default="dictionary_consolidation_v1", pattern=r"^dictionary_consolidation_v1$")
    revision: str = Field(min_length=1)
    base_dictionary_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parent_draft_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    change_notes: str = Field(min_length=1)
    component_types: list[ComponentType]
    attributes: list[AttributeDefinition]
    alias_additions: list[AliasAddition] = Field(default_factory=list)
    type_bindings: list[TypeBinding]
    decisions: list[MappingDecision]


@dataclass(frozen=True)
class AnalysisInput:
    document: ParsedEvidenceDocument
    composition: CompositionProposal
    discovery: DiscoveryProposal
    composition_sha256: str
    discovery_sha256: str


CONSOLIDATION_INSTRUCTIONS = """모든 문서의 원문 관찰과 의미 후보를 비교해 사전 정의를 제안한다.
속성명 유사성만으로 병합하지 않는다. 의미·차원·측정 기준·장착/지원·개별/전체를 비교한다.
SSD/HDD, 시스템/GPU 메모리, 기본/부스트 클럭, 정확도/정밀도를 구별한다.
모든 관찰에 MAP/HOLD/EXCLUDE를 하나씩 부여하고 이유를 쓴다. 강제로 매핑하지 않는다.
구성요소 유형은 문서별 실제 대상과 구분하며 적용 유형을 명시한다.
동의어는 실제 원문 인용과 적용 문맥을 가진다. 사전에는 공고의 요구값을 복사하지 않는다.
기존 승인 사전이 있으면 정의를 덮어쓰지 않고 재사용하거나 신규 정의를 제안한다.
기존 정의의 새 동의어는 alias_additions로 제안한다. 의미 변경·병합·분할은 별도 검토 대상으로 남긴다.
수정 시 parent_draft_sha256과 change_notes를 기록한다. 최종 검토를 수행한 것으로 주장하지 않는다.
"""


UNIT_DIMENSIONS = {
    **{u: "data_size" for u in ["B", "KB", "MB", "GB", "TB", "PB", "KiB", "MiB", "GiB", "TiB"]},
    **{u: "frequency" for u in ["Hz", "kHz", "MHz", "GHz", "Ghz"]},
    **{u: "power" for u in ["W", "kW", "mW", "WATT"]},
    **{u: "length" for u in ["mm", "㎜", "cm", "m", "µm", "μm", "nm", "인치", "inch"]},
    **{u: "count" for u in ["개", "대", "EA", "ea", "Core", "core", "코어", "Thread", "thread", "Port", "port", "포트"]},
    **{u: "time" for u in ["s", "ms", "min", "h", "초", "분", "시간"]},
    **{u: "mass" for u in ["kg", "g", "mg"]},
    **{u: "pressure" for u in ["Pa", "kPa", "MPa"]},
    **{u: "temperature" for u in ["°C", "℃", "K"]},
    **{u: "data_rate" for u in ["Gbps", "Gb/s", "MB/s", "GbE", "Gigabit"]},
    "U": "rack_height", "MT/s": "transfer_rate", "GT/s": "transfer_rate",
    "RPM": "rotation_rate", "V": "voltage", "DWPD": "write_endurance",
    "lux": "illuminance", "fps": "frame_rate", "%": "ratio",
}


def build_dictionary_draft(
    inputs: list[AnalysisInput], proposal: ConsolidationProposal, *, batch_id: str,
    source_bundle_sha256: str, source_notices: list[str], source_hashes: list[str],
    base: dict | None = None, base_sha256: str | None = None,
    previous: dict | None = None, previous_sha256: str | None = None,
) -> dict:
    if proposal.base_dictionary_sha256 != base_sha256 or proposal.parent_draft_sha256 != previous_sha256:
        raise ValueError("base/parent dictionary hash mismatch")
    if previous is not None:
        if (previous["source_bundle_sha256"] != source_bundle_sha256 or previous["revision"] == proposal.revision
                or previous["batch_id"] != batch_id or previous["base_dictionary_sha256"] != base_sha256):
            raise ValueError("revision must change and retain source batch")
    if base is not None and base.get("status") != "offline_approved":
        raise ValueError("only an offline approved dictionary can be the next batch base")
    base_catalogue = base["catalogue"] if base else {"component_types": [], "attributes": []}
    old_notices = base.get("source_notices", []) if base else []
    old_sources = base.get("source_hashes", []) if base else []
    if set(old_notices) & set(source_notices) or set(old_sources) & set(source_hashes):
        raise ValueError("next batch repeats an approved notice or source document")
    types = [ComponentType.model_validate(t) for t in base_catalogue["component_types"]] + [
        t.model_copy(deep=True) for t in proposal.component_types]
    attributes = [AttributeDefinition.model_validate(a) for a in base_catalogue["attributes"]] + [
        a.model_copy(deep=True) for a in proposal.attributes]
    type_map = {t.type_id: t for t in types}
    attribute_map = {a.attribute_id: a for a in attributes}
    errors = []
    if len(type_map) != len(types) or len(attribute_map) != len(attributes):
        errors.append("duplicate_or_redefined_dictionary_id")
    documents = [i.document for i in inputs]
    if len({d.document_id for d in documents}) != len(documents):
        raise ValueError("duplicate document in analysis")
    observations = {}
    targets = {}
    for item in inputs:
        doc_id = item.document.document_id
        errors.extend(f"{doc_id}:{e}" for e in validate_discovery(
            item.discovery, item.composition, item.document, composition_sha256=item.composition_sha256))
        observations.update({f"{doc_id}/{o.observation_id}": o for o in item.discovery.observations})
        targets.update({f"{doc_id}/{t.target_id}": t for t in item.composition.targets})
    bindings = {f"{b.document_id}/{b.target_id}": b for b in proposal.type_bindings}
    if len(bindings) != len(proposal.type_bindings):
        errors.append("duplicate_type_binding")
    for key, binding in bindings.items():
        if key not in targets or targets[key].role not in {"root", "primary", "detail"} or binding.type_id not in type_map:
            errors.append(f"{key}:invalid_type_binding")
    for definition in [*proposal.component_types, *proposal.attributes]:
        for alias in definition.aliases:
            errors.extend(validate_evidence(alias.evidence, documents))
            if not comparable_text(alias.expression) or not any(
                    comparable_text(alias.expression) in comparable_text(e.quote) for e in alias.evidence):
                errors.append("alias_not_in_evidence")
    alias_review_ids = []
    for index, addition in enumerate(proposal.alias_additions):
        target = (type_map if addition.target_kind == "component_type" else attribute_map).get(addition.target_id)
        alias = addition.alias
        errors.extend(validate_evidence(alias.evidence, documents))
        if not comparable_text(alias.expression) or not any(
                comparable_text(alias.expression) in comparable_text(e.quote) for e in alias.evidence):
            errors.append("alias_not_in_evidence")
        if target is None:
            errors.append("alias_target_not_found")
        elif any((comparable_text(a.expression), comparable_text(a.context)) ==
                 (comparable_text(alias.expression), comparable_text(alias.context)) for a in target.aliases):
            errors.append("duplicate_alias_addition")
        else:
            target.aliases.append(alias)
        alias_review_ids.append(f"alias:{addition.target_kind}/{addition.target_id}/{index}")
    for a in attributes:
        if len(set(a.component_type_ids)) != len(a.component_type_ids) or not set(a.component_type_ids) <= type_map.keys():
            errors.append(f"{a.attribute_id}:invalid_applicable_types")
        for unit in [*a.accepted_raw_units, *([a.canonical_unit] if a.canonical_unit else [])]:
            if UNIT_DIMENSIONS.get(unit) != a.meaning.dimension:
                errors.append(f"{a.attribute_id}:unit_dimension_unverified")
        if a.meaning.dimension != "none" and (not a.canonical_unit or not a.accepted_raw_units):
            errors.append(f"{a.attribute_id}:missing_units")
        if a.meaning.dimension == "none" and (a.canonical_unit is not None or a.accepted_raw_units):
            errors.append(f"{a.attribute_id}:unexpected_units")
        if "unknown" in a.meaning.signature():
            errors.append(f"{a.attribute_id}:unknown_attribute_scope")
    decisions = {d.observation_ref: d for d in proposal.decisions}
    if len(decisions) != len(proposal.decisions) or decisions.keys() != observations.keys():
        errors.append("decisions_do_not_cover_observations_exactly")
    used = set()
    requirements = []
    for key, observation in observations.items():
        decision = decisions.get(key)
        if decision is None:
            continue
        if observation.kind != "property" and decision.decision != "EXCLUDE":
            errors.append(f"{key}:work_requirement_must_not_be_an_attribute")
        if decision.decision != "MAP":
            if decision.attribute_id is not None:
                errors.append(f"{key}:non_map_has_attribute")
            if decision.decision == "HOLD":
                errors.append(f"{key}:unresolved_mapping")
        else:
            attribute = attribute_map.get(decision.attribute_id)
            owner_key = key.split("/")[0] + "/" + observation.owner_id
            binding = bindings.get(owner_key)
            if attribute is None:
                errors.append(f"{key}:unknown_attribute")
            else:
                used.add(attribute.attribute_id)
                if attribute.meaning.signature() != observation.meaning.signature():
                    errors.append(f"{key}:meaning_scope_mismatch")
                if binding is None or binding.type_id not in attribute.component_type_ids:
                    errors.append(f"{key}:component_type_mismatch")
                if observation.unit_raw is not None and observation.unit_raw not in attribute.accepted_raw_units:
                    errors.append(f"{key}:unit_not_accepted")
                if attribute.meaning.dimension not in {"none", "count"} and observation.unit_raw is None:
                    errors.append(f"{key}:missing_observation_unit")
        requirements.append({"observation_ref": key, "observation": observation.model_dump(),
                             "mapping": decision.model_dump()})
    if {a.attribute_id for a in proposal.attributes} - used:
        errors.append("new_attribute_without_mapped_evidence")
    if not used:
        errors.append("no_mapped_attributes_in_batch")
    new_type_ids = {t.type_id for t in proposal.component_types}
    if new_type_ids - {b.type_id for b in bindings.values()}:
        errors.append("new_type_without_target_binding")
    names = [comparable_text(a.name) for a in attributes]
    if len(names) != len(set(names)):
        errors.append("duplicate_attribute_display_name_requires_resolution")
    review_ids = sorted(
        [f"observation:{key}" for key in observations]
        + [f"attribute:{key}" for key in used | {a.attribute_id for a in proposal.attributes}]
        + [f"component_type:{key}" for key in {b.type_id for b in proposal.type_bindings}]
        + [f"coverage:{d.document_id}" for d in documents]
        + [f"logic:{d.document_id}" for d in documents]
        + ["dictionary:duplicate_meanings"] + alias_review_ids
    )
    return {
        "schema_version": "bootstrap_draft_v1", "status": "draft", "batch_id": batch_id,
        "revision": proposal.revision, "source_bundle_sha256": source_bundle_sha256,
        "base_dictionary_sha256": base_sha256, "parent_draft_sha256": previous_sha256,
        "change_notes": proposal.change_notes,
        "source_notices": old_notices + source_notices, "source_hashes": old_sources + source_hashes,
        "input_hashes": {i.document.document_id: {"composition": i.composition_sha256,
                                                "discovery": i.discovery_sha256} for i in inputs},
        "catalogue": {"component_types": [t.model_dump() for t in types],
                      "attributes": [a.model_dump() for a in attributes]},
        "requirements": requirements,
        "condition_groups": {i.document.document_id: [g.model_dump() for g in i.discovery.groups] for i in inputs},
        "blocking_issues": sorted(set(errors)), "required_review_ids": review_ids,
        "semantic_review_status": "pending", "normalized_values_produced": False,
        "limitations": {i.document.document_id: i.discovery.limitations for i in inputs},
    }
