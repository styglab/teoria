"""Item-first, evidence-grounded contracts for offline specification analysis."""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .document_evidence import EvidenceQuote, ParsedEvidenceDocument, comparable_text, validate_evidence

Predicate = Literal["component_of", "specifies", "physical_part_of", "delivery_member_of", "logical_role_of",
                    "service_for", "reference_to", "connected_to", "compatible_with", "related_to"]
Dimension = Literal["count", "data_size", "frequency", "power", "length", "time", "data_rate",
                    "rack_height", "transfer_rate", "ratio", "identifier", "categorical", "boolean", "text", "unknown"]
Role = Literal["delivery_target", "delivery_group", "specification_subject", "physical_component", "component",
               "logical_role", "existing", "external", "service", "document_group", "unknown"]
UNIT_DIMENSIONS = {
    **{u: "data_size" for u in ["B", "KB", "MB", "GB", "TB", "PB", "KiB", "MiB", "GiB", "TiB"]},
    **{u: "count" for u in ["개", "대", "식", "EA", "ea", "Core", "core", "코어", "Thread", "thread", "Port", "port", "포트"]},
    **{u: "frequency" for u in ["Hz", "kHz", "MHz", "GHz"]},
    **{u: "power" for u in ["W", "kW", "WATT"]},
    **{u: "length" for u in ["mm", "cm", "m", "인치", "inch"]},
    **{u: "time" for u in ["s", "ms", "h", "초", "분", "시간"]},
    **{u: "data_rate" for u in ["Gbps", "Gb/s", "MB/s"]},
    "U": "rack_height", "MT/s": "transfer_rate", "%": "ratio",
}



class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(Record):
    entity_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label_raw: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    roles: list[Role] = Field(min_length=1)
    owner_item_id: str | None
    evidence: list[EvidenceQuote] = Field(min_length=1)


InventoryCategory = Literal["delivery_item", "bundle", "component", "service", "existing", "external", "unknown"]
INVENTORY_ROLES = {"delivery_item": "delivery_target", "bundle": "delivery_group",
                   "component": "component", "service": "service",
                   "existing": "existing", "external": "external", "unknown": "unknown"}


class InventoryEntity(Entity):
    # One structural role; contextual meanings belong in meaning, never extra role tags.
    roles: list[Literal["delivery_target", "delivery_group", "component", "service",
                        "existing", "external", "unknown"]] = Field(min_length=1, max_length=1)


class ParentLink(Record):
    parent_id: str
    predicate: Literal["component_of", "physical_part_of", "delivery_member_of", "service_for"]
    basis: Literal["explicit", "interpreted", "ambiguous"]
    evidence: list[EvidenceQuote] = Field(min_length=1)
    reason: str = Field(min_length=1)


class InventoryEntry(Record):
    entity: InventoryEntity
    category: InventoryCategory
    parent: ParentLink | None
    status: Literal["supported", "candidate"]
    node_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class ItemInventory(Record):
    schema_version: Literal["composition_inventory_v3"] = "composition_inventory_v3"
    document_id: str
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    purchase_summary: str = Field(min_length=1)
    scope_evidence: list[EvidenceQuote] = Field(min_length=1)
    entries: list[InventoryEntry]
    shared_node_ids: list[str]
    unresolved_node_ids: list[str]
    issues: list[str]


class Qualifiers(Record):
    aggregation: Literal["per_instance", "total", "per_module", "per_slot", "not_applicable", "unknown"]
    configuration: Literal["installed", "supported", "existing", "not_applicable", "unknown"]
    measurement_basis: str = Field(min_length=1)


class Requirement(Record):
    requirement_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    subject_id: str | None
    item_ids: list[str]
    scope: Literal["item", "common", "cross_item", "unknown"]
    kind: Literal["property", "functional", "service", "delivery", "other"]
    property_raw: str | None = Field(description="Exact source attribute label, or null when the attribute is implicit. Put inferred meaning in meaning.")
    meaning: str = Field(min_length=1)
    dimension: Dimension
    value_text: str = Field(min_length=1)
    unit_raw: str | None
    operator: Literal["eq", "ge", "gt", "le", "lt", "range", "in", "required", "prohibited", "qualitative", "unknown"]
    operator_raw: str | None
    modality: Literal["required", "recommended", "unknown"]
    qualifiers: Qualifiers
    evidence: list[EvidenceQuote] = Field(min_length=1)


class Relation(Record):
    relation_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    subject_id: str
    predicate: Predicate
    object_id: str
    basis: Literal["explicit", "interpreted", "ambiguous"]
    reason: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class ConditionGroup(Record):
    group_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    logic: Literal["and", "or", "if"]
    members: list[str] = Field(min_length=1)
    antecedents: list[str] = Field(default_factory=list)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class Coverage(Record):
    node_id: str
    status: Literal["observed", "non_requirement", "partial", "deferred"]
    requirement_ids: list[str]
    reason: str = Field(min_length=1)



class IdentityLink(Record):
    alias_id: str
    canonical_id: str
    reason: str = Field(min_length=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class DocumentAnalysis(Record):
    schema_version: Literal["semantic_document_v2"] = "semantic_document_v2"
    document_id: str
    native_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    entities: list[Entity]
    requirements: list[Requirement]
    relations: list[Relation]
    groups: list[ConditionGroup]
    coverage: list[Coverage]
    identities: list[IdentityLink]
    issues: list[str]


class ItemExtraction(Record):
    """One inventory item's source region, or the shared/unassigned source region."""
    document_id: str
    native_sha256: str
    task_id: str
    entities: list[Entity]
    requirements: list[Requirement]
    relations: list[Relation]
    groups: list[ConditionGroup]
    coverage: list[Coverage]
    issues: list[str]


class SubjectAssignment(Record):
    requirement_id: str
    subject_id: str | None
    item_ids: list[str]
    scope: Literal["item", "common", "cross_item", "unknown"]


class ResolutionProposal(Record):
    document_id: str
    native_sha256: str
    identities: list[IdentityLink]
    assignments: list[SubjectAssignment]
    relations: list[Relation]
    cross_task_groups: list[ConditionGroup] = Field(default_factory=list)
    issues: list[str]


class Finding(Record):
    item_id: str
    category: Literal["item_missing", "item_split", "wrong_owner", "quantity_scope", "unsupported_relation",
                      "missing_requirement", "source_error", "ambiguity"]
    severity: Literal["error", "ambiguity"]
    description: str = Field(min_length=1)


class DocumentValidation(Record):
    graph_sha256: str
    checked_item_ids: list[str]
    findings: list[Finding]
    limitations: list[str] = Field(min_length=1)


class Definition(Record):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["entity", "property", "relation"]
    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    dimension: Dimension | None
    applicable_entity_concept_ids: list[str]
    aliases: list[str]
    distinction: str = Field(min_length=1)
    predicate: Predicate | None = None


class Mapping(Record):
    observation_ref: str
    decision: Literal["map", "hold", "exclude"]
    concept_id: str | None
    reason: str = Field(min_length=1)


class ConceptRelation(Record):
    subject_id: str
    predicate: Literal["subtype_of", "related_to"]
    object_id: str
    reason: str = Field(min_length=1)


class Integration(Record):
    schema_version: Literal["semantic_dictionary_draft_v2"] = "semantic_dictionary_draft_v2"
    definitions: list[Definition]
    mappings: list[Mapping]
    concept_relations: list[ConceptRelation]
    issues: list[str]


def unique(items, label):
    if len(items) != len(set(items)):
        raise ValueError(f"duplicate {label}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _grounded(text: str, quotes: list[EvidenceQuote]) -> bool:
    if not comparable_text(text):
        return False
    # Numeric tokens must not match the middle of a different number/model token.
    normalized = unicodedata.normalize("NFKC", text)
    if re.fullmatch(r"[+\-−]?\d+(?:[.,]\d+)*", normalized):
        return any(re.search(r"(?<![\w.,+\-−])" + re.escape(normalized) + r"(?![\d.,])",
                             unicodedata.normalize("NFKC", e.quote)) for e in quotes)
    return any(comparable_text(text) in comparable_text(e.quote) for e in quotes)



def text_node_ids(document):
    return {n.node_id for n in document.nodes if n.kind != "image" and n.text.strip()}


def validate_inventory(inventory: ItemInventory, document: ParsedEvidenceDocument) -> None:
    require((inventory.document_id, inventory.native_sha256) == (document.document_id, document.native_sha256),
            "inventory identity/hash mismatch")
    unique([entry.entity.entity_id for entry in inventory.entries], "inventory entity")
    text = text_node_ids(document)
    require(not validate_evidence(inventory.scope_evidence, [document]), "invalid purchase scope evidence")
    entries = {e.entity.entity_id: e for e in inventory.entries}
    parents = {e.entity.entity_id: [e.parent.parent_id] for e in inventory.entries if e.parent}
    require(all(p in entries for values in parents.values() for p in values), "unknown inventory parent")
    _acyclic(parents)
    allocated = set()
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    for entry in inventory.entries:
        entity = entry.entity
        check(entity.roles == [INVENTORY_ROLES[entry.category]],
                f"{entity.entity_id}/roles: category {entry.category} requires {[INVENTORY_ROLES[entry.category]]}")
        if entry.parent:
            link = entry.parent
            require(link.parent_id in entries and link.parent_id != entity.entity_id,
                    f"{entity.entity_id}/parent: unknown or self parent {link.parent_id}")
            require(not validate_evidence(link.evidence, [document]), f"{entity.entity_id}: invalid parent evidence")
            require(entry.category != "delivery_item" or link.predicate == "delivery_member_of" and entries[link.parent_id].category == "bundle", f"{entity.entity_id}: internal objects are components, not independent delivery items")
            require(link.predicate != "delivery_member_of" or entries[link.parent_id].category == "bundle",
                    f"{entity.entity_id}: delivery membership requires bundle parent")
        elif entry.category == "component":
            require(entry.status == "candidate", f"{entity.entity_id}: supported component requires parent")
        ancestor = entry
        expected_owner = None
        ambiguous_path = False
        while ancestor.parent and entry.category != "delivery_item":
            ambiguous_path |= ancestor.parent.basis == "ambiguous"
            ancestor = entries[ancestor.parent.parent_id]
            if ancestor.category == "delivery_item":
                expected_owner = ancestor.entity.entity_id
                break
        if entry.category == "service":
            # The serviced existing asset is not necessarily the purchasing item.
            check(entity.owner_item_id is None or entity.owner_item_id in entries and
                    entries[entity.owner_item_id].category == "delivery_item",
                    f"{entity.entity_id}/owner_item_id: service owner must be a delivery item or null")
        else:
            check(entity.owner_item_id == expected_owner or
                    entry.status == "candidate" and ambiguous_path and entity.owner_item_id is None,
                f"{entity.entity_id}/owner_item_id: expected root delivery item {expected_owner}")
        require(not validate_evidence(entity.evidence, [document]), "invalid inventory evidence")
        require(_grounded(entity.label_raw, entity.evidence), "inventory label absent from evidence")
        unique(entry.node_ids, "inventory source node")
        check(set(entry.node_ids) <= text,
              f"{entity.entity_id}/node_ids: non-text or unknown IDs {sorted(set(entry.node_ids) - text)}")
        require({e.node_id for e in entity.evidence} <= set(entry.node_ids), "inventory evidence outside source region")
        allocated.update(entry.node_ids)
    for field in ("shared_node_ids", "unresolved_node_ids"):
        refs = getattr(inventory, field)
        unique(refs, "inventory source node")
        check(set(refs) <= text, f"{field}: non-text or unknown IDs {sorted(set(refs) - text)}")
        allocated.update(refs)
    check(text <= allocated, f"inventory must account for every text node; missing={sorted(text - allocated)}")
    require(not errors, "invalid inventory:\n" + "\n".join(errors))


def canonical_ids(graph: DocumentAnalysis) -> dict[str, str]:
    entities = {e.entity_id: e for e in graph.entities}
    unique([i.alias_id for i in graph.identities], "identity alias")
    aliases = {i.alias_id: i.canonical_id for i in graph.identities}
    for alias, target in aliases.items():
        require(alias in entities and target in entities and alias != target, "invalid identity endpoint")
    _acyclic({key: [value] for key, value in aliases.items()})
    result = {}
    for key in entities:
        target = key
        while target in aliases:
            target = aliases[target]
        result[key] = target
    return result


def _acyclic(links):
    visiting, done = set(), set()
    def visit(key):
        require(key not in visiting, "cycle in semantic structure")
        if key in done:
            return
        visiting.add(key)
        for target in links.get(key, []):
            visit(target)
        visiting.remove(key)
        done.add(key)
    for key in links:
        visit(key)


def validate_analysis(analysis: DocumentAnalysis, document: ParsedEvidenceDocument, *, node_ids=None) -> None:
    require((analysis.document_id, analysis.native_sha256) == (document.document_id, document.native_sha256),
            "document identity/hash mismatch")
    entities = {e.entity_id: e for e in analysis.entities}
    requirements = {r.requirement_id: r for r in analysis.requirements}
    ids = [e.entity_id for e in analysis.entities] + list(requirements)
    ids += [r.relation_id for r in analysis.relations] + [g.group_id for g in analysis.groups]
    require(len(requirements) == len(analysis.requirements), "duplicate requirement")
    unique(ids, "analysis ID")
    canonical = canonical_ids(analysis)
    items = {canonical[e.entity_id] for e in analysis.entities if "delivery_target" in e.roles}
    for record in [*analysis.entities, *analysis.requirements, *analysis.relations, *analysis.groups, *analysis.identities]:
        require(not validate_evidence(record.evidence, [document]), "invalid source evidence")
    for entity in analysis.entities:
        unique(entity.roles, "entity role")
        require(_grounded(entity.label_raw, entity.evidence), "entity label absent from evidence")
        owner = entity.owner_item_id
        require(owner is None or owner in canonical and canonical[owner] in items, "unknown owner item")
        require("delivery_target" not in entity.roles or owner is None, "delivery item cannot be an internal scope")
        if owner:
            require(canonical[owner] != canonical[entity.entity_id], "component cannot own itself")
    for identity in analysis.identities:
        alias, target = entities[identity.alias_id], entities[identity.canonical_id]
        require(("delivery_target" in alias.roles) == ("delivery_target" in target.roles),
                "cannot merge a delivery item with an internal scope")
        require(canonical.get(alias.owner_item_id) == canonical.get(target.owner_item_id),
                "cannot merge scopes of different items")
        anchored = {e.node_id for e in identity.evidence}
        require(all(anchored & {e.node_id for e in entity.evidence} for entity in (alias, target)),
                "identity must cite both target observations")
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    for requirement in analysis.requirements:
        require(requirement.subject_id is None or requirement.subject_id in entities, "unknown requirement subject")
        unique(requirement.item_ids, "requirement item")
        require(all(key in canonical and canonical[key] in items for key in requirement.item_ids), "unknown requirement item")
        owners = {canonical[key] for key in requirement.item_ids}
        if requirement.scope == "item":
            require(len(owners) == 1, "item requirement needs one owner")
        elif requirement.scope == "cross_item":
            require(len(owners) >= 2, "cross-item requirement needs multiple items")
        if requirement.subject_id:
            subject = entities[canonical[requirement.subject_id]]
            owner = canonical[subject.entity_id] if "delivery_target" in subject.roles else canonical.get(subject.owner_item_id)
            require(owner is None or owner in owners, "requirement assigned to a different item's scope")
        require(re.fullmatch(r"[a-z][a-z0-9_]*", requirement.dimension) is not None, "dimension must be snake_case")
        for field in ("property_raw", "value_text", "unit_raw", "operator_raw"):
            value = getattr(requirement, field)
            check(value is None or _grounded(value, requirement.evidence),
                  f"requirement text absent from evidence: {requirement.requirement_id}/{field}; "
                  "property_raw may be null when the attribute label is implicit")
        operators = {"이상": "ge", "이하": "le", "초과": "gt", "미만": "lt", "≥": "ge", "≤": "le", ">=": "ge", "<=": "le"}
        if requirement.operator_raw in operators:
            check(requirement.operator == operators[requirement.operator_raw],
                  f"operator contradicts source: {requirement.requirement_id}")
        dimension = UNIT_DIMENSIONS.get(requirement.unit_raw)
        if dimension:
            check(requirement.dimension in {dimension, "unknown"},
                    f"source unit dimension mismatch: {requirement.requirement_id} unit={requirement.unit_raw} "
                    f"requires {dimension} or unknown; got {requirement.dimension}")
    physical, delivery = {}, {}
    for relation in analysis.relations:
        require(relation.subject_id in entities and relation.object_id in entities, "unknown relation endpoint")
        subject, target = canonical[relation.subject_id], canonical[relation.object_id]
        require(subject != target, "self relation after identity resolution")
        if relation.predicate in {"physical_part_of", "component_of"}:
            if "delivery_target" in entities[subject].roles:
                check(relation.basis == "explicit", f"{relation.relation_id}: physical containment of delivery items requires explicit evidence")
            physical.setdefault(subject, []).append(target)
        if relation.predicate == "delivery_member_of":
            check("delivery_group" in entities[target].roles,
                  f"{relation.relation_id}: delivery membership requires a bundle; "
                  "internal specification scopes use specifies, included services use service_for")
            delivery.setdefault(subject, []).append(target)
        if relation.predicate in {"physical_part_of", "component_of", "specifies"}:
            def owner(key):
                row = entities[key]
                return key if "delivery_target" in row.roles else canonical.get(row.owner_item_id)
            left, right = owner(subject), owner(target)
            both_items = "delivery_target" in entities[subject].roles and "delivery_target" in entities[target].roles
            check(both_items and relation.predicate == "physical_part_of" or left is None or right is None or left == right,
                  f"{relation.relation_id}: internal relation crosses delivery items")
    _acyclic(physical)
    _acyclic(delivery)
    groups = {g.group_id: g for g in analysis.groups}
    links = {}
    for group in analysis.groups:
        refs = group.members + group.antecedents
        unique(refs, "condition reference")
        require(set(refs) <= (requirements.keys() | groups.keys()), "unknown condition reference")
        require((group.logic == "if") == bool(group.antecedents), "invalid conditional group")
        require(group.logic == "if" or len(group.members) >= 2, "invalid logical group")
        links[group.group_id] = [ref for ref in refs if ref in groups]
    _acyclic(links)
    text = text_node_ids(document) if node_ids is None else set(node_ids)
    unique([c.node_id for c in analysis.coverage], "coverage node")
    require({c.node_id for c in analysis.coverage} == text, "incomplete node coverage")
    expected = {(e.node_id, r.requirement_id) for r in analysis.requirements for e in r.evidence}
    actual = set()
    for coverage in analysis.coverage:
        unique(coverage.requirement_ids, "coverage requirement")
        require(set(coverage.requirement_ids) <= requirements.keys(), "unknown coverage requirement")
        require(coverage.status != "observed" or bool(coverage.requirement_ids), "observed node without requirement")
        require(coverage.status != "non_requirement" or not coverage.requirement_ids, "non-requirement node has conditions")
        actual.update((coverage.node_id, ref) for ref in coverage.requirement_ids)
    check(actual == expected, "coverage/evidence mismatch")
    require(not errors, "invalid analysis:\n" + "\n".join(errors))


def apply_resolution(original: DocumentAnalysis, proposal: ResolutionProposal) -> DocumentAnalysis:
    require((proposal.document_id, proposal.native_sha256) == (original.document_id, original.native_sha256),
            "resolution identity/hash mismatch")
    result = original.model_copy(deep=True)
    result.identities = proposal.identities
    canonical = canonical_ids(result)
    rows = {r.requirement_id: r for r in result.requirements}
    unique([a.requirement_id for a in proposal.assignments], "subject assignment")
    for assignment in proposal.assignments:
        require(assignment.requirement_id in rows, "unknown assigned requirement")
        row = rows[assignment.requirement_id]
        row.subject_id, row.item_ids, row.scope = assignment.subject_id, assignment.item_ids, assignment.scope
    for row in result.requirements:
        row.subject_id = canonical.get(row.subject_id, row.subject_id)
        row.item_ids = list(dict.fromkeys(canonical.get(key, key) for key in row.item_ids))
    require(all(g.group_id.startswith("resolved_") for g in proposal.cross_task_groups),
            "cross-task group ID must start with resolved_")
    result.groups.extend(proposal.cross_task_groups)
    result.relations = proposal.relations
    result.issues = list(dict.fromkeys([*original.issues, *proposal.issues]))
    return result


def validate_resolved(original: DocumentAnalysis, resolved: DocumentAnalysis) -> None:
    def observations(graph):
        return {r.requirement_id: r.model_dump(exclude={"subject_id", "item_ids", "scope"}) for r in graph.requirements}
    require(observations(original) == observations(resolved), "resolution changed source observations")
    preserved = {r.relation_id: r for r in original.relations if r.relation_id.startswith("structure_")}
    actual = {r.relation_id: r for r in resolved.relations}
    changed = sorted(key for key, row in preserved.items() if actual.get(key) != row)
    require(not changed, f"resolution changed reviewed composition: copy these relation IDs unchanged: {changed}")
    require(original.entities == resolved.entities, "resolution changed entity observations")
    require(original.coverage == resolved.coverage and original.groups == resolved.groups[:len(original.groups)],
            "resolution changed coverage/logic")


def validation_items(graph: DocumentAnalysis) -> list[str]:
    return sorted(["document/" + graph.document_id, "items/completeness", "requirements/completeness",
                   *["entity/" + e.entity_id for e in graph.entities],
                   *["requirement/" + r.requirement_id for r in graph.requirements],
                   *["relation/" + r.relation_id for r in graph.relations],
                   *["identity/" + i.alias_id for i in graph.identities],
                   *["group/" + g.group_id for g in graph.groups]])


def observations(analyses: list[DocumentAnalysis]) -> dict:
    result = {}
    for analysis in analyses:
        for kind, rows, field in [("entity", analysis.entities, "entity_id"),
                                  ("property", analysis.requirements, "requirement_id"),
                                  ("relation", analysis.relations, "relation_id")]:
            for row in rows:
                result[f"{analysis.document_id}/{getattr(row, field)}"] = (kind, row)
    return result


def validate_integration(draft: Integration, analyses: list[DocumentAnalysis]) -> None:
    unique([d.concept_id for d in draft.definitions], "concept ID")
    unique([m.observation_ref for m in draft.mappings], "mapping")
    source = observations(analyses)
    supplied = {m.observation_ref for m in draft.mappings}
    require(supplied == source.keys(), "mappings must cover every observation exactly once; "
            f"missing={sorted(source.keys() - supplied)}, extra={sorted(supplied - source.keys())}")
    definitions = {d.concept_id: d for d in draft.definitions}
    mappings = {m.observation_ref: m for m in draft.mappings}
    used = set()
    for mapping in draft.mappings:
        kind, row = source[mapping.observation_ref]
        if mapping.decision != "map":
            require(mapping.concept_id is None, "non-map decision has concept")
            continue
        definition = definitions.get(mapping.concept_id)
        require(definition is not None and definition.kind == kind, "mapping kind mismatch")
        if kind == "property":
            require(row.kind == "property", "work/functional condition cannot become a property")
            require(definition.dimension == row.dimension, "property dimension mismatch")
            require(row.subject_id is not None and row.scope != "unknown", "unresolved property subject must remain on hold")
            if row.subject_id is not None:
                document_id = mapping.observation_ref.split("/", 1)[0]
                subject = mappings[f"{document_id}/{row.subject_id}"]
                require(subject.decision == "map", "unresolved property subject must remain on hold")
                require(subject.concept_id in definition.applicable_entity_concept_ids,
                        "property mapped outside applicable entity types")
        if kind == "relation":
            require(definition.predicate == row.predicate, "relation predicate mismatch")
        used.add(mapping.concept_id)
    # Abstract parent concepts may be justified by hierarchy, rather than direct occurrences.
    related = set()
    hierarchy = {}
    for relation in draft.concept_relations:
        require(relation.subject_id in definitions and relation.object_id in definitions, "unknown concept endpoint")
        require(relation.subject_id != relation.object_id, "self concept relation")
        require(definitions[relation.subject_id].kind == definitions[relation.object_id].kind, "cross-kind concept hierarchy")
        related.update([relation.subject_id, relation.object_id])
        if relation.predicate == "subtype_of":
            hierarchy.setdefault(relation.subject_id, []).append(relation.object_id)
    _acyclic(hierarchy)
    require(set(definitions) <= used | related, "unsupported unused definition")
    for definition in draft.definitions:
        require(all(key in definitions and definitions[key].kind == "entity"
                    for key in definition.applicable_entity_concept_ids), "invalid applicable entity concept")
        require(definition.kind != "property" or bool(definition.dimension), "property dimension required")
        occurrences = [source[m.observation_ref][1] for m in draft.mappings
                       if m.decision == "map" and m.concept_id == definition.concept_id]
        require(all(any(_grounded(alias, row.evidence) for row in occurrences) for alias in definition.aliases),
                "alias absent from mapped source evidence")


    for graph in analyses:
        for identity in graph.identities:
            alias = mappings[f"{graph.document_id}/{identity.alias_id}"]
            target = mappings[f"{graph.document_id}/{identity.canonical_id}"]
            require((alias.decision, alias.concept_id) == (target.decision, target.concept_id),
                    "same target observations have inconsistent concept mappings")
