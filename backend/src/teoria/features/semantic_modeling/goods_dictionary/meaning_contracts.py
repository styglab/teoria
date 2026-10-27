"""Versioned business definitions and explicit source-expression mappings."""
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from teoria.features.semantic_modeling.goods_dictionary.contracts import Record


class ConceptDefinition(Record):
    key: str = Field(pattern=r'^[a-z][a-z0-9_]{0,119}$')
    kind: Literal['item_type', 'characteristic']
    preferred_name: str = Field(min_length=1, max_length=300)
    definition: str = Field(min_length=10, max_length=4000)
    value_kind: Literal['number', 'text', 'range', 'tolerance', 'dimensions', 'set', 'expression', 'relative', 'all', 'any'] | None = None
    applicable_item_type_ids: list[UUID] = Field(default_factory=list, max_length=100)
    quantity_dimension: str | None = Field(default=None, max_length=100)
    canonical_unit: str | None = Field(default=None, max_length=100)
    allowed_units: list[str] = Field(default_factory=list, max_length=100)
    references: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode='after')
    def meaningful_shape(self):
        if any(not r.strip() for r in self.references):
            raise ValueError('definition references cannot be blank')
        if len(set(self.applicable_item_type_ids)) != len(self.applicable_item_type_ids):
            raise ValueError('duplicate applicability')
        if self.kind == 'item_type':
            if self.value_kind or self.applicable_item_type_ids or self.quantity_dimension or self.canonical_unit or self.allowed_units:
                raise ValueError('item type cannot declare characteristic constraints')
        elif not self.value_kind or not self.applicable_item_type_ids:
            raise ValueError('characteristic needs a value kind and explicit applicable item types')
        if self.quantity_dimension or self.canonical_unit or self.allowed_units:
            if not self.quantity_dimension or not self.canonical_unit or self.canonical_unit not in self.allowed_units:
                raise ValueError('unit policy needs dimension and an allowed canonical unit')
        return self


class MeaningDecision(Record):
    action: Literal['approve', 'reject', 'deprecate']
    rationale: str = Field(min_length=10, max_length=4000)


class MappingProposal(Record):
    source_entry_id: UUID
    target_revision_id: UUID
    classification_code: str | None = Field(default=None, pattern=r'^\d{10}$')
    owner_concept_id: UUID | None = None
    relation: Literal['equivalent', 'related'] = 'equivalent'
    rationale: str = Field(min_length=10, max_length=4000)


class MeaningResolution(Record):
    source_entry_ids: list[UUID] = Field(max_length=1000)
    classification_code: str | None = Field(default=None, pattern=r'^\d{10}$')
