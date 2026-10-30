"""Versioned business definitions and explicit source-expression mappings."""
from typing import Literal
from uuid import UUID, uuid5

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
    scope_mode: Literal['classified','unclassified','independent'] | None = None

    @model_validator(mode='after')
    def explicit_scope(self):
        self.scope_mode = self.scope_mode or ('classified' if self.classification_code else 'unclassified')
        if (self.scope_mode=='classified') != (self.classification_code is not None):
            raise ValueError('classified scope requires a code; other scopes cannot carry a code')
        return self


class MeaningResolution(Record):
    source_entry_ids: list[UUID] = Field(max_length=1000)
    classification_code: str | None = Field(default=None, pattern=r'^\d{10}$')


def concept_id_for_key(key):
    return uuid5(UUID('3b790e06-dd7b-4fc3-b1d8-8832380578e9'), key)


class DefinitionChange(Record):
    base_revision_id: UUID | None = None
    definition: ConceptDefinition


class MappingChange(Record):
    source_entry_id: UUID
    target_key: str
    owner_key: str | None = None
    classification_code: str | None = Field(default=None, pattern=r'^\d{10}$')
    rationale: str = Field(min_length=10, max_length=4000)
    scope_mode: Literal['classified','unclassified','independent'] | None = None

    @model_validator(mode='after')
    def explicit_scope(self):
        self.scope_mode = self.scope_mode or ('classified' if self.classification_code else 'unclassified')
        if (self.scope_mode=='classified') != (self.classification_code is not None):
            raise ValueError('invalid classification scope')
        return self


class DictionaryChangeSet(Record):
    baseline_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    definitions: list[DefinitionChange] = Field(default_factory=list, max_length=1000)
    mappings: list[MappingChange] = Field(default_factory=list, max_length=5000)
    retire_concept_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    reviewed_source_sha256: list[str] = Field(default_factory=list,max_length=100000)
    rationale: str = Field(min_length=10, max_length=4000)

    @model_validator(mode='after')
    def unique_changes(self):
        import re
        if any(not re.fullmatch(r'[a-f0-9]{64}',value) for value in self.reviewed_source_sha256):
            raise ValueError('reviewed sources require SHA256 hashes')
        keys = [d.definition.key for d in self.definitions]
        scopes = [(m.source_entry_id, m.classification_code,m.scope_mode) for m in self.mappings]
        if len(keys) != len(set(keys)) or len(scopes) != len(set(scopes)):
            raise ValueError('duplicate definition or source scope in changeset')
        if len(self.retire_concept_ids) != len(set(self.retire_concept_ids)):
            raise ValueError('duplicate retired concept')
        return self


class RelatedMeaningContext(Record):
    source_entry_ids: list[UUID] = Field(default_factory=list,max_length=5000)
    concept_ids: list[UUID] = Field(default_factory=list,max_length=1000)
    changes: DictionaryChangeSet | None = None


class DictionarySnapshot(Record):
    schema_version: Literal[1] = 1
    artifact_kind: Literal['goods_dictionary_snapshot'] = 'goods_dictionary_snapshot'
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    concepts: list[dict]
    mappings: list[dict]
    sources: list[dict]

    @model_validator(mode='after')
    def verify_checksum(self):
        from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum
        if self.checksum != dictionary_checksum(self.content()):
            raise ValueError('dictionary snapshot checksum mismatch')
        return self

    def content(self):
        return {'concepts': self.concepts, 'mappings': self.mappings, 'sources': self.sources}


def snapshot_from_records(concepts, mappings, sources):
    """A deterministic snapshot of meaning state, excluding clocks, actors and evidence bodies."""
    import json
    from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum
    fields = [('concepts', concepts, ('revision_id','concept_id','concept_key','revision','kind','content','status')),
              ('mappings', mappings, ('mapping_id','source_entry_id','target_revision_id','classification_code','owner_concept_id','relation','status')),
              ('sources', sources, ('entry_id','kind','owner_entry_id','status','preferred_name'))]
    body = {}
    for name, records, keys in fields:
        values = [{**{k: r.get(k) for k in keys},
                   **({'scope_mode':r['scope_mode']} if name=='mappings' and 'scope_mode' in r else {})} for r in records]
        body[name] = sorted(json.loads(json.dumps(values, default=str)), key=lambda row: dictionary_checksum(row))
    return DictionarySnapshot(checksum=dictionary_checksum(body), **body)


def approved_dictionary_snapshot(snapshot):
    """Unresolved source registrations do not create new semantic releases."""
    snapshot=DictionarySnapshot.model_validate(snapshot)
    concepts=[c for c in snapshot.concepts if c['status']=='approved']
    revisions={c['revision_id'] for c in concepts}
    mappings=[m for m in snapshot.mappings if m['status']=='approved' and m['target_revision_id'] in revisions]
    ids={m['source_entry_id'] for m in mappings}
    while True:
        owners={s.get('owner_entry_id') for s in snapshot.sources if s['entry_id'] in ids}-{None}
        if owners.issubset(ids):break
        ids.update(owners)
    return snapshot_from_records(concepts,mappings,[s for s in snapshot.sources if s['entry_id'] in ids])


def scope_matches(mapping, classification_code, *, legacy=False):
    mode=mapping.get('scope_mode')
    if mode is None:
        if legacy:
            return mapping['classification_code'] in {None,classification_code}
        mode='classified' if mapping['classification_code'] else 'unclassified'
    return (mode=='independent' or (mode=='unclassified' and classification_code is None)
            or (mode=='classified' and classification_code is not None and mapping['classification_code']==classification_code))


def resolve_snapshot(snapshot, source_entry_ids, classification_code=None):
    """Pure resolution shared by pinned document runs and change impact checks."""
    snapshot = DictionarySnapshot.model_validate(snapshot)
    concepts = {str(c['revision_id']): c for c in snapshot.concepts if c['status']=='approved'}
    sources = {str(s['entry_id']): s for s in snapshot.sources}
    mappings = [m for m in snapshot.mappings if m['status']=='approved' and m['relation']=='equivalent'
                and str(m['target_revision_id']) in concepts
                and scope_matches(m,classification_code,legacy='scope_mode' not in m)]
    results = {}
    def resolve(entry_id, path=frozenset()):
        key = str(entry_id)
        if key in results:
            return results[key]
        row = {'source_entry_id': key, 'status':'unresolved', 'reason':'no_approved_scoped_equivalence'}
        source = sources.get(key)
        if not source or source.get('status') not in {None,'approved'}:
            return {**row, 'reason':'source_not_found'}
        if key in path:
            return {**row, 'reason':'cyclic_owner'}
        choices = [m for m in mappings if str(m['source_entry_id'])==key]
        if source['kind']=='characteristic':
            owner = resolve(source['owner_entry_id'], path|{key})
            choices = [m for m in choices if owner['status']=='resolved' and str(m['owner_concept_id'])==owner['concept_id']]
        targets = {str(m['target_revision_id']) for m in choices}
        if len(targets)>1:
            row.update(status='held',reason='ambiguous_approved_mappings')
        elif targets:
            target = concepts[next(iter(targets))]
            row.update(status='resolved',reason='approved_scoped_equivalence',concept_id=str(target['concept_id']),
                revision_id=str(target['revision_id']),concept_key=target['concept_key'],kind=target['kind'],
                definition=target['content'],mapping_ids=[str(m['mapping_id']) for m in choices])
        results[key] = row
        return row
    return {'policy_version':'approved_scoped_equivalence_v1', 'snapshot_checksum':snapshot.checksum,
            'items':[resolve(entry) for entry in source_entry_ids]}
