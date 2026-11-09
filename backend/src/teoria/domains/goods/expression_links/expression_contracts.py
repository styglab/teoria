"""Expression links and compiled snapshots of published Ontology meaning.

Definitions in a snapshot are immutable publication copies, never authoring records.
Legacy dictionary snapshots remain readable through snapshot_contracts.
"""
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from teoria.domains.goods.expression_links.contracts import Record, dictionary_checksum
from teoria.domains.goods.expression_links.snapshot_contracts import scope_matches
from teoria.platform.ontology.authoring.publication_contracts import OntologyPublicationRef as OntologyReference


class OntologyMappingProposal(Record):
    source_entry_id: UUID
    ontology: OntologyReference
    target_concept_id: UUID
    owner_concept_id: UUID | None = None
    classification_code: str | None = Field(default=None, pattern=r'^\d{10}$')
    scope_mode: Literal['classified', 'unclassified', 'independent'] = 'unclassified'
    relation: Literal['equivalent', 'related'] = 'equivalent'
    rationale: str = Field(min_length=10, max_length=4000)

    @model_validator(mode='after')
    def valid_scope(self):
        if (self.scope_mode == 'classified') != (self.classification_code is not None):
            raise ValueError('classified scope requires a code; other scopes cannot carry a code')
        return self


class DictionaryDraftImport(Record):
    ontology_draft_id: UUID
    revision_ids: list[UUID] = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=10, max_length=4000)


def published_concepts(content, reference):
    """Read canonical definitions directly from the publication, with stable identities."""
    result = []
    for obj in content['objects']:
        for item, kind, owner in [(obj, 'item_type', None), *[
            (prop, 'characteristic', str(obj['concept_id'])) for prop in obj['properties']
        ]]:
            value_type = item.get('value_type')
            result.append({
                'concept_id': str(item['concept_id']), 'concept_key': item['stable_key'],
                'kind': kind, 'status': 'approved', 'ontology': reference,
                'owner_concept_id': owner,
                'content': {'key': item['stable_key'], 'kind': kind,
                    'preferred_name': item['name'], 'definition': item['description'],
                    'value_kind': ('number' if value_type in {'integer','number','decimal','float','double'}
                                   else 'text' if value_type in {'string','text'} else None),
                    'value_type': value_type, 'canonical_unit': item.get('unit'),
                    'applicable_item_type_ids': [owner] if owner else [],
                    'quantity_dimension': item.get('quantity_dimension'),
                    'references': [], 'allowed_units': item.get('allowed_units', [])},
            })
    return result


class OntologyDictionarySnapshot(Record):
    schema_version: Literal[2] = 2
    artifact_kind: Literal['goods_expression_snapshot'] = 'goods_expression_snapshot'
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    ontologies: list[dict]
    mappings: list[dict]
    sources: list[dict]

    def content(self):
        return {'ontologies': self.ontologies, 'mappings': self.mappings, 'sources': self.sources}

    @model_validator(mode='after')
    def verified(self):
        if self.checksum != dictionary_checksum(self.content()):
            raise ValueError('expression snapshot checksum mismatch')
        versions = set()
        for artifact in self.ontologies:
            ref = OntologyReference.model_validate(artifact['ontology'])
            body = artifact['content']
            if (dictionary_checksum(body) != ref.checksum or
                (body['namespace'], body['version']) != (ref.namespace, ref.version)):
                raise ValueError('ontology artifact checksum or identity mismatch')
            if str(ref.version_id) in versions:
                raise ValueError('duplicate ontology version')
            versions.add(str(ref.version_id))
        concepts = {(c['ontology']['version_id'], c['concept_id']): c for c in self.concepts}
        for mapping in self.mappings:
            key = (str(mapping['ontology_version_id']), str(mapping['target_concept_id']))
            target = concepts.get(key)
            if target is None or target['owner_concept_id'] != (
                str(mapping['owner_concept_id']) if mapping.get('owner_concept_id') else None
            ):
                raise ValueError('mapping target or owner absent from pinned publication')
        return self

    @property
    def concepts(self):
        return [c for a in self.ontologies for c in published_concepts(a['content'], a['ontology'])]


def expression_snapshot(ontologies, mappings, sources):
    import json
    body = {key: sorted(json.loads(json.dumps(rows, default=str)), key=dictionary_checksum)
            for key, rows in [('ontologies', ontologies), ('mappings', mappings), ('sources', sources)]}
    return OntologyDictionarySnapshot(checksum=dictionary_checksum(body), **body)


def approved_expression_snapshot(snapshot):
    mappings = [m for m in snapshot.mappings if m['status'] == 'approved']
    ids = {str(m['source_entry_id']) for m in mappings}
    while True:
        parents = {str(s['owner_entry_id']) for s in snapshot.sources
                   if str(s['entry_id']) in ids and s.get('owner_entry_id')}
        if parents.issubset(ids):
            break
        ids.update(parents)
    versions = {str(m['ontology_version_id']) for m in mappings}
    return expression_snapshot(
        [a for a in snapshot.ontologies if a['ontology']['version_id'] in versions], mappings,
        [s for s in snapshot.sources if str(s['entry_id']) in ids])


def resolve_expression_snapshot(snapshot, entry_ids, classification_code):
    sources = {str(s['entry_id']): s for s in snapshot.sources}
    concepts = {(c['ontology']['version_id'], c['concept_id']): c for c in snapshot.concepts}
    mappings = [m for m in snapshot.mappings if m['status'] == 'approved'
                and m['relation'] == 'equivalent' and scope_matches(m, classification_code)]
    resolved = {}

    def resolve(entry_id, path=frozenset()):
        key = str(entry_id)
        if key in resolved:
            return resolved[key]
        row = {'source_entry_id': key, 'status': 'unresolved', 'reason': 'no_approved_ontology_mapping'}
        source = sources.get(key)
        if not source or source.get('status') != 'approved':
            return {**row, 'reason': 'source_not_found'}
        if key in path:
            return {**row, 'reason': 'cyclic_owner'}
        choices = [m for m in mappings if str(m['source_entry_id']) == key]
        if source['kind'] == 'characteristic':
            owner = resolve(source['owner_entry_id'], path | {key})
            choices = [m for m in choices if owner['status'] == 'resolved'
                       and str(m['owner_concept_id']) == owner['concept_id']
                       and str(m['ontology_version_id']) == owner['ontology']['version_id']]
        choices = [m for m in choices if concepts[(str(m['ontology_version_id']), str(m['target_concept_id']))]['kind'] == source['kind']]
        targets = {(str(m['ontology_version_id']), str(m['target_concept_id'])) for m in choices}
        if len(targets) > 1:
            row.update(status='held', reason='ambiguous_approved_mappings')
        elif targets:
            target = concepts[next(iter(targets))]
            row.update(status='resolved', reason='approved_ontology_mapping',
                       concept_id=target['concept_id'], ontology=target['ontology'],
                       revision_id=target['ontology']['version_id'] + ':' + target['concept_id'],
                       concept_key=target['concept_key'], kind=target['kind'], definition=target['content'],
                       mapping_ids=[str(m['mapping_id']) for m in choices])
        resolved[key] = row
        return row

    return {'policy_version': 'published_ontology_expression_v2', 'snapshot_checksum': snapshot.checksum,
            'items': [resolve(entry_id) for entry_id in entry_ids]}
