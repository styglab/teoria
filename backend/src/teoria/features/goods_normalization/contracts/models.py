"""Semantic references and executable, context-specific normalization policies."""
from decimal import Decimal
import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical_bytes(value):
    if isinstance(value, BaseModel):value=value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def checksum(value):return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid', hide_input_in_errors=True)


class OntologyReference(Record):
    version_id: UUID
    namespace: str = Field(min_length=1)
    version: str = Field(min_length=1)
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')


class Concept(Record):
    concept_id: UUID
    stable_key: str = Field(min_length=1)
    kind: Literal['object', 'property', 'relationship']
    object_concept_id: UUID | None = None
    source_object_concept_id: UUID | None = None
    target_object_concept_id: UUID | None = None
    value_type: str | None = None
    unit: str | None = None


class EntityRule(Record):
    rule_id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    aliases: list[str] = Field(min_length=1)
    source_kinds: list[str] = Field(default_factory=lambda:['equipment'])
    concept_id: UUID


class UnitRule(Record):
    source_unit: str = Field(min_length=1)
    canonical_unit: str = Field(min_length=1)
    multiplier: Decimal = Field(default=Decimal('1'), gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def supported_conversion(self):
        scales={'B':Decimal(1),'kB':Decimal(1000),'MB':Decimal(1000)**2,'GB':Decimal(1000)**3,
                'TB':Decimal(1000)**4,'KiB':Decimal(1024),'MiB':Decimal(1024)**2,
                'GiB':Decimal(1024)**3,'TiB':Decimal(1024)**4}
        count_aliases={'EA':'개','ea':'개'}
        if count_aliases.get(self.source_unit,self.source_unit)==count_aliases.get(self.canonical_unit,self.canonical_unit):expected=Decimal(1)
        elif self.source_unit in scales and self.canonical_unit in scales:
            expected=scales[self.source_unit]/scales[self.canonical_unit]
        else:raise ValueError('unsupported unit conversion; preserve as an unresolved candidate')
        if self.multiplier!=expected:raise ValueError('incorrect unit conversion multiplier')
        return self


class RequirementRule(Record):
    rule_id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    target_concept_id: UUID
    property_concept_id: UUID
    source_property_keys: list[str] = Field(min_length=1)
    roles: list[Literal['requirement_candidate','supported_capability','existing_reference','recommended','optional']] = Field(min_length=1)
    scopes: list[Literal['per_item','per_package','per_reference_quantity','batch_total','per_component','system_total','per_module','per_processor','support_limit','service']] = Field(min_length=1)
    value_type: Literal['number','text','identifier']
    units: list[UnitRule] = Field(default_factory=list)

    @model_validator(mode='after')
    def distinct_units(self):
        if self.value_type=='number' and not self.units:raise ValueError('numeric rules require explicit unit policies')
        if self.value_type!='number' and self.units:raise ValueError('only numeric rules may convert units')
        if len({u.source_unit for u in self.units})!=len(self.units):raise ValueError('ambiguous source unit policies')
        return self


class RelationRule(Record):
    rule_id: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    source_kind: str = Field(min_length=1)
    relationship_concept_id: UUID
    reverse: bool = False


class NormalizationProfile(Record):
    schema_version: Literal[1] = 1
    profile_key: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    version: str = Field(min_length=1)
    classification_code: str = Field(pattern=r'^\d{10}$')
    ontology: OntologyReference
    entities: list[EntityRule] = Field(min_length=1)
    requirements: list[RequirementRule] = Field(default_factory=list)
    relations: list[RelationRule] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_rule_ids(self):
        ids=[r.rule_id for r in [*self.entities,*self.requirements,*self.relations]]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate rule IDs')
        return self


class NormalizationPackage(Record):
    schema_version: Literal[2] = 2
    artifact_kind: Literal['goods_normalization_package'] = 'goods_normalization_package'
    profile_revision_id: UUID
    profile_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    profile: NormalizationProfile
    concepts: list[Concept]
    approval_actor: str = Field(min_length=1)
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def verify_contract(self):
        if self.profile_checksum!=checksum(self.profile):raise ValueError('profile checksum mismatch')
        if self.checksum!=checksum(self.model_dump(mode='json', exclude={'checksum'})):
            raise ValueError('normalization package checksum mismatch')
        concepts={c.concept_id:c for c in self.concepts}
        if len(concepts)!=len(self.concepts):raise ValueError('duplicate concepts')
        def require(identifier,kind):
            c=concepts.get(identifier)
            if c is None or c.kind!=kind:raise ValueError('unknown or incorrect concept kind')
            return c
        for rule in self.profile.entities:require(rule.concept_id,'object')
        for rule in self.profile.requirements:
            require(rule.target_concept_id,'object');prop=require(rule.property_concept_id,'property')
            if prop.object_concept_id!=rule.target_concept_id:raise ValueError('property belongs to another target type')
            types={'number':{'integer','number','decimal','float','double'},'text':{'string','text'},'identifier':{'string','text'}}
            if prop.value_type not in types[rule.value_type]:raise ValueError('property value type mismatch')
            if rule.units and any(u.canonical_unit!=prop.unit for u in rule.units):raise ValueError('canonical unit differs from ontology property')
        for rule in self.profile.relations:
            rel=require(rule.relationship_concept_id,'relationship')
            require(rel.source_object_concept_id,'object');require(rel.target_object_concept_id,'object')
        return self
