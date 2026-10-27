"""Reviewable document goods graphs, independent of classification and publication.

This contract describes document requirements. It never creates installed assets,
approves meanings, evaluates arbitrary formulas, or invokes a Runtime Capability.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from teoria.features.goods_normalization.contracts.models import Record


class SourceEvidence(Record):
    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class SpecificationValue(Record):
    """Tagged values; formulas and relative boundaries remain unevaluated."""

    kind: Literal[
        "number", "text", "range", "tolerance", "dimensions", "set",
        "expression", "relative", "all", "any",
    ]
    number: Decimal | None = Field(default=None, allow_inf_nan=False)
    text: str | None = None
    unit_raw: str | None = None
    unit_ref: str | None = None
    reference: str | None = Field(default=None, min_length=1)
    arguments: list[SpecificationValue] = Field(default_factory=list)
    dimension_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def value_shape(self):
        supplied = {
            key for key in self.model_fields_set
            if getattr(self, key) is not None and getattr(self, key) != []
        }
        common = {"kind", "unit_raw", "unit_ref"}
        shape = {
            "number": ({"number"}, {"number"}),
            "text": ({"text"}, {"text"}),
            "expression": ({"text"}, {"text", "reference"}),
            "relative": ({"reference", "number"}, {"reference", "number"}),
            "range": ({"arguments"}, {"arguments"}),
            "tolerance": ({"number"}, {"number"}),
            "dimensions": ({"arguments", "dimension_names"}, {"arguments", "dimension_names"}),
            "set": ({"arguments"}, {"arguments"}),
            "all": ({"arguments"}, {"arguments"}),
            "any": ({"arguments"}, {"arguments"}),
        }
        required, allowed = shape[self.kind]
        if not required <= supplied or supplied - common - allowed:
            raise ValueError("value fields do not match the selected value kind")
        if self.kind == "range":
            if len(self.arguments) != 2 or any(v.kind not in {"number", "relative"} for v in self.arguments):
                raise ValueError("range requires two numeric or relative boundaries")
            low, high = self.arguments
            if low.kind == high.kind == "number":
                if (low.unit_raw, low.unit_ref) != (high.unit_raw, high.unit_ref):
                    raise ValueError("range boundaries require the same unit representation")
                if low.number > high.number:
                    raise ValueError("range boundaries are reversed")
        if self.kind == "tolerance" and self.number < 0:
            raise ValueError("tolerance magnitude must be nonnegative")
        if self.kind == "dimensions":
            if len(self.arguments) != len(self.dimension_names) or not self.arguments:
                raise ValueError("each dimension needs a name and value")
            if len(set(self.dimension_names)) != len(self.dimension_names):
                raise ValueError("dimension names must be distinct")
            if any(value.kind not in {"number", "relative"} for value in self.arguments):
                raise ValueError("dimension values must be numeric or relative")
        if self.kind in {"all", "any"} and len(self.arguments) < 2:
            raise ValueError("logical expressions require at least two arguments")
        if self.kind == "set" and not self.arguments:
            raise ValueError("set values must not be empty")
        if self.text is not None and not self.text.strip():
            raise ValueError("text expressions must not be blank")
        return self


class EvidenceBacked(Record):
    evidence_ids: list[str] = Field(min_length=1)
    evidence_basis: Literal["explicit", "interpreted", "unresolved"] = "explicit"


class SpecificationSubject(EvidenceBacked):
    subject_id: str = Field(min_length=1)
    kind: Literal["item", "service", "context", "deliverable"]
    name: str = Field(min_length=1)
    context_kind: Literal["location", "functional_group", "test_subject", "reference_model", "measurand"] | None = None
    type_ref: str | None = None

    @model_validator(mode="after")
    def context_has_a_role(self):
        if (self.kind == "context") != (self.context_kind is not None):
            raise ValueError("context_kind is required exclusively for context subjects")
        return self


class SupplyScope(EvidenceBacked):
    scope_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Quantity(Record):
    value: Decimal = Field(ge=0, allow_inf_nan=False)
    operator: Literal["eq", "gte", "lte", "gt", "lt"] = "eq"
    unit_raw: str = Field(min_length=1)
    scope_raw: str = Field(min_length=1)


class SupplyMembership(EvidenceBacked):
    membership_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    role: Literal[
        "required_supply", "optional_supply", "existing", "externally_provided",
        "test_subject", "reference_only", "excluded", "unresolved",
    ]
    quantity: Quantity | None = None


class CompositionStatement(EvidenceBacked):
    composition_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    child_id: str = Field(min_length=1)
    relation_kind: Literal["physical_component", "system_member", "accessory"]
    quantity: Quantity | None = None
    inclusion_role: Literal["required", "optional", "excluded", "unresolved"] = "required"


class ItemRelationStatement(EvidenceBacked):
    relation_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation_kind: Literal["installed_on", "compatible_with", "data_connection", "power_connection"]
    conditions_raw: list[str] = Field(default_factory=list)


class SpecificationCondition(Record):
    description: str = Field(min_length=1)
    value: SpecificationValue | None = None


class PropertySpecification(EvidenceBacked):
    statement_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    characteristic_ref: str = Field(min_length=1)
    value: SpecificationValue
    operator: Literal["eq", "gte", "lte", "gt", "lt", "described"] = "described"
    assertion_role: Literal["requirement", "supported_capability", "description", "reference", "optional"] = "requirement"
    semantic_scope: str = Field(min_length=1)
    conditions: list[SpecificationCondition] = Field(default_factory=list)


class StandardCitation(Record):
    identifier_raw: str = Field(min_length=1)
    edition_raw: str | None = None
    clause_raw: str | None = None
    allows_equivalent: bool = False


class RequirementSpecification(EvidenceBacked):
    requirement_id: str = Field(min_length=1)
    requirement_kind: Literal[
        "functional", "interoperation", "service", "compliance", "acceptance",
        "warranty", "documentation", "safety",
    ]
    text: str = Field(min_length=1)
    subject_ids: list[str] = Field(min_length=1)
    conditions: list[SpecificationCondition] = Field(default_factory=list)
    trigger_raw: str | None = None
    standards: list[StandardCitation] = Field(default_factory=list)
    verifies: list[str] = Field(default_factory=list)


class ClassificationClaim(Record):
    assignment_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    raw_code: str = Field(min_length=1)
    source_kind: Literal["document", "item_metadata", "reviewed_inference"]
    source_ref: str = Field(min_length=1)
    resolution_status: Literal["unresolved", "verified", "conflicting", "rejected"] = "unresolved"
    catalog_ref: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def classification_is_not_guessed(self):
        if self.source_kind == "document" and not self.evidence_ids:
            raise ValueError("document classification requires evidence")
        if self.resolution_status == "verified" and not self.catalog_ref:
            raise ValueError("verified classification requires a verified catalog reference")
        if self.resolution_status in {"unresolved", "conflicting", "rejected"} and self.catalog_ref:
            raise ValueError("unresolved classification must not select a catalog entry")
        return self


class DocumentGoodsGraph(Record):
    schema_version: Literal[1] = 1
    document_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_status: Literal["proposed"] = "proposed"
    evidence: list[SourceEvidence] = Field(min_length=1)
    subjects: list[SpecificationSubject] = Field(min_length=1)
    supply_scopes: list[SupplyScope] = Field(default_factory=list)
    memberships: list[SupplyMembership] = Field(default_factory=list)
    compositions: list[CompositionStatement] = Field(default_factory=list)
    item_relations: list[ItemRelationStatement] = Field(default_factory=list)
    properties: list[PropertySpecification] = Field(default_factory=list)
    requirements: list[RequirementSpecification] = Field(default_factory=list)
    classifications: list[ClassificationClaim] = Field(default_factory=list)

    @model_validator(mode="after")
    def graph_references_and_ownership(self):
        subjects = {s.subject_id: s for s in self.subjects}
        scopes = {s.scope_id for s in self.supply_scopes}
        evidence = {e.evidence_id for e in self.evidence}
        identities = [s.subject_id for s in self.subjects] + [s.scope_id for s in self.supply_scopes]
        identities += [e.evidence_id for e in self.evidence]
        for rows, field in [
            (self.memberships, "membership_id"), (self.compositions, "composition_id"),
            (self.item_relations, "relation_id"), (self.properties, "statement_id"),
            (self.requirements, "requirement_id"), (self.classifications, "assignment_id"),
        ]:
            identities += [getattr(row, field) for row in rows]
        if len(identities) != len(set(identities)):
            raise ValueError("graph IDs must be unique within a document revision")
        for row in [*self.subjects, *self.supply_scopes, *self.memberships, *self.compositions,
                    *self.item_relations, *self.properties, *self.requirements, *self.classifications]:
            if not set(row.evidence_ids) <= evidence:
                raise ValueError("unknown evidence reference")

        def subject(identifier, kinds=None):
            found = subjects.get(identifier)
            if found is None or (kinds and found.kind not in kinds):
                raise ValueError("missing subject or incorrect subject kind")
            return found

        roles = {}
        for member in self.memberships:
            if member.scope_id not in scopes:
                raise ValueError("unknown supply scope")
            s = subject(member.subject_id)
            if s.kind == "context" and member.role in {"required_supply", "optional_supply"}:
                raise ValueError("a context is not a supplied product")
            roles.setdefault(member.subject_id, []).append(member)
        adjacency = {}
        for comp in self.compositions:
            subject(comp.parent_id, {"item"}); subject(comp.child_id, {"item"})
            if comp.parent_id == comp.child_id:
                raise ValueError("a product cannot contain itself")
            if comp.inclusion_role != "excluded":
                adjacency.setdefault(comp.parent_id, []).append(comp.child_id)
            for parent in roles.get(comp.parent_id, []):
                for child in roles.get(comp.child_id, []):
                    if parent.scope_id == child.scope_id and comp.inclusion_role == "required":
                        if parent.role == "required_supply" and child.role in {"excluded", "reference_only", "test_subject"}:
                            raise ValueError("required composition contradicts the supply role")
        visited, visiting = set(), set()

        def visit(identifier):
            if identifier in visiting:
                raise ValueError("cyclic product composition")
            if identifier in visited:
                return
            visiting.add(identifier)
            for child in adjacency.get(identifier, []):
                visit(child)
            visiting.remove(identifier); visited.add(identifier)

        for identifier in adjacency:
            visit(identifier)
        for relation in self.item_relations:
            subject(relation.source_id, {"item"}); subject(relation.target_id, {"item"})
            if relation.source_id == relation.target_id:
                raise ValueError("item relations require distinct subjects")
        for prop in self.properties:
            subject(prop.subject_id, {"item", "context"})
        requirement_ids = {r.requirement_id for r in self.requirements}
        property_ids = {p.statement_id for p in self.properties}
        for req in self.requirements:
            if len(req.subject_ids) != len(set(req.subject_ids)):
                raise ValueError("requirement subjects must be distinct")
            for identifier in req.subject_ids:
                if identifier not in scopes:
                    subject(identifier)
            if req.verifies:
                if req.requirement_kind != "acceptance" or not set(req.verifies) <= (requirement_ids | property_ids):
                    raise ValueError("acceptance must reference existing properties or requirements")
                if set(req.verifies) & {r.requirement_id for r in self.requirements if r.requirement_kind == "acceptance"}:
                    raise ValueError("acceptance criteria cannot verify other acceptance criteria")
        for claim in self.classifications:
            subject(claim.subject_id, {"item"})
        return self


class DocumentGoodsGraphBatch(Record):
    purpose: str = Field(min_length=1)
    graphs: list[DocumentGoodsGraph] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_document_revisions(self):
        keys = [(g.document_id, g.revision_id) for g in self.graphs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate document revision")
        return self
