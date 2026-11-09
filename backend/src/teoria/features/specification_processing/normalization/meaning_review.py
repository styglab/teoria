"""Evidence-backed owner/scope interpretations alongside frozen source observations.

Inputs are proposals, including when authored by an agent. This produces a
review artifact only: no extraction mutation, approvals, profiles or DB writes.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from teoria.features.semantic_modeling.ontology.publication_contracts import publication_checksum
from teoria.features.semantic_modeling.ontology.review_contracts import OntologyReviewRef, OntologyReviewSnapshot
from teoria.features.specification_processing.extraction.attribute_resolution import Resolution
from teoria.features.specification_processing.extraction.value_normalization import number
from teoria.features.specification_processing.models import Record, StandardReference
from teoria.features.specification_processing.normalization.ontology_alignment import SOURCE_ROLES, anchors
from teoria.features.specification_processing.parsing.document_evidence import EvidenceQuote, attribute_is_grounded, literal

SourceScope = Resolution.model_fields['scope'].annotation


class EntityMeaningProposal(Record):
    subject_id: str = Field(min_length=1)
    concept_id: UUID
    evidence: list[EvidenceQuote] = Field(min_length=1)
    rationale: str = Field(min_length=10, max_length=2000)


class PropertyMeaningProposal(Record):
    observation_id: str = Field(min_length=1)
    concept_id: UUID
    subject_id: str = Field(min_length=1)
    semantic_scope: SourceScope
    evidence: list[EvidenceQuote] = Field(min_length=1)
    rationale: str = Field(min_length=10, max_length=2000)


class MeaningReviewInput(Record):
    schema_version: Literal[1] = 1
    review_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    result: StandardReference
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    ontology: OntologyReviewRef
    entities: list[EntityMeaningProposal] = Field(min_length=1, max_length=100)
    properties: list[PropertyMeaningProposal] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_selections(self):
        if len({e.subject_id for e in self.entities}) != len(self.entities):
            raise ValueError('duplicate_review_subject')
        if len({p.observation_id for p in self.properties}) != len(self.properties):
            raise ValueError('duplicate_review_property')
        return self


def _evidence_error(quotes, document, observation):
    nodes = {n['node_id']: n for n in document['parsed_document']['nodes']}
    if any(q.document_id != document['document_id'] or q.node_id not in nodes for q in quotes):
        return 'review_evidence_reference_mismatch'
    if any(nodes[q.node_id]['kind'] == 'image' or not literal(q.quote)
           or literal(q.quote) not in literal(nodes[q.node_id]['text']) for q in quotes):
        return 'review_quote_not_in_source'
    if not anchors(observation).intersection(q.node_id for q in quotes):
        return 'review_evidence_does_not_anchor_observation'
    return None


def _property_error(observation, proposal, catalog, entity_links, document):
    reason = _evidence_error(proposal.evidence, document, observation)
    if reason:
        return reason
    if not attribute_is_grounded(document, observation):
        return 'source_condition_mismatch'
    concept = catalog.get(str(proposal.concept_id))
    if concept is None or concept['kind'] != 'property':
        return 'review_property_not_in_context'
    owner = entity_links.get(proposal.subject_id)
    if owner is None:
        return 'review_subject_unresolved'
    if owner != concept['owner_concept_id']:
        return 'review_property_owner_mismatch'
    if proposal.semantic_scope == 'unknown' or observation.get('semantic_role') not in SOURCE_ROLES:
        return 'review_role_or_scope_unresolved'
    if concept['value_type'] in {'decimal', 'integer', 'number', 'float', 'double'}:
        value = number(observation['value_raw']) if observation['data_type'] == 'number' else None
        if value is None:
            return 'review_numeric_value_unresolved'
        if concept['value_type'] == 'integer' and Decimal(value) != Decimal(value).to_integral_value():
            return 'review_integer_value_required'
        allowed = set(concept['allowed_units']) | ({concept['unit']} if concept['unit'] else set())
        if observation.get('unit_raw') not in (allowed or {None}):
            return 'review_unit_not_allowed'
    elif concept['value_type'] in {'string', 'text'}:
        if observation['data_type'] not in {'text', 'identifier'} or observation.get('unit_raw') is not None:
            return 'review_value_type_mismatch'
    else:
        return 'review_value_type_unsupported'
    return None


def build_meaning_review(request: MeaningReviewInput, result: dict, snapshot: OntologyReviewSnapshot):
    """Validate candidate structure/evidence; semantic equivalence requires review."""
    snapshot = OntologyReviewSnapshot.model_validate(snapshot.model_dump(mode='json'))
    if snapshot.context != request.ontology:
        raise ValueError('review_context_mismatch')
    if (result.get('artifact_kind') != 'specification_document_result'
            or result.get('document_id') != request.document_id):
        raise ValueError('review_requires_document_result')
    before = publication_checksum(result)
    documents = result['extracted']['documents']
    matches = [d for d in documents if d['document_id'] == request.document_id]
    if len(matches) != 1:
        raise ValueError('review_document_missing_or_ambiguous')
    document = matches[0]
    if result['source_sha256'] != request.source_sha256 or document['source']['sha256'] != request.source_sha256:
        raise ValueError('review_source_hash_mismatch')
    entities = {e['id']: e for e in document['entities']}
    attributes = {a['id']: a for a in document['attributes']}
    if len(entities) != len(document['entities']) or len(attributes) != len(document['attributes']):
        raise ValueError('duplicate_source_observation')
    catalog = snapshot.concept_catalog()
    rows, entity_links = [], {}
    for proposal in request.entities:
        observation = entities.get(proposal.subject_id)
        if observation is None:
            raise ValueError('review_entity_not_in_source')
        concept = catalog.get(str(proposal.concept_id))
        reason = _evidence_error(proposal.evidence, document, observation)
        if reason is None and (concept is None or concept['kind'] != 'object'):
            reason = 'review_object_not_in_context'
        if reason is None:
            entity_links[proposal.subject_id] = str(proposal.concept_id)
        rows.append({'kind': 'entity', 'observation_id': proposal.subject_id,
            'status': 'held' if reason else 'requires_review', 'reason': reason,
            'source': deepcopy(observation), 'interpretation': proposal.model_dump(mode='json'),
            'concept_key': concept['stable_key'] if concept else None})
    for proposal in request.properties:
        observation = attributes.get(proposal.observation_id)
        if observation is None:
            raise ValueError('review_attribute_not_in_source')
        reason = _property_error(observation, proposal, catalog, entity_links, document)
        changes = []
        if observation['subject_ids'] != [proposal.subject_id]:
            changes.append('subject_ids')
        if observation.get('semantic_scope', 'unknown') != proposal.semantic_scope:
            changes.append('semantic_scope')
        concept = catalog.get(str(proposal.concept_id))
        rows.append({'kind': 'property', 'observation_id': proposal.observation_id,
            'status': 'held' if reason else 'requires_review', 'reason': reason,
            'source': deepcopy(observation), 'interpretation': proposal.model_dump(mode='json'),
            'changes': changes, 'concept_key': concept['stable_key'] if concept else None})
    if publication_checksum(result) != before:
        raise ValueError('review_source_observations_changed')
    counts = Counter(row['status'] for row in rows)
    report = {'schema_version': 1, 'artifact_kind': 'specification_meaning_review',
        'review_id': request.review_id, 'authority': 'suggestion', 'mode': 'review_only',
        'auto_applied': False, 'published': False, 'semantic_equivalence_confirmed': False,
        'ontology_context': request.ontology.model_dump(mode='json'),
        'request_checksum': publication_checksum(request.model_dump(mode='json')),
        'source_result': request.result.model_dump(mode='json'), 'source_result_checksum': before,
        'source_sha256': request.source_sha256, 'document_id': request.document_id,
        'observations_unchanged': True,
        'summary': {'selected_observations': len(rows), 'requires_review': counts['requires_review'],
                    'held': counts['held'], 'source_entities': len(entities), 'source_attributes': len(attributes),
                    'unselected_entities': len(entities) - len(request.entities),
                    'unselected_attributes': len(attributes) - len(request.properties),
                    'proposed_interpretation_changes': sum(bool(row.get('changes')) for row in rows)},
        'observations': rows}
    return {**report, 'checksum': publication_checksum(report)}


async def prepare_meaning_review(request: MeaningReviewInput, output_root: str, *, api=None):
    from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
    from teoria.features.specification_processing.storage.artifact_store import artifact_store, read_uri
    raw = await read_uri(request.result.uri)
    if hashlib.sha256(raw).hexdigest() != request.result.sha256:
        raise ValueError('review_result_bytes_changed')
    payload = json.loads(raw)
    result = payload.get('result', payload)
    if api is None:
        async with GoodsAuthoringClient() as client:
            snapshot = await client.ontology_review_version(request.ontology)
    else:
        snapshot = await api.ontology_review_version(request.ontology)
    report = build_meaning_review(request, result, snapshot)
    async with artifact_store(output_root) as store:
        manifest = await store.put(request.review_id + '/request.json',
            json.dumps(request.model_dump(mode='json'), ensure_ascii=False, sort_keys=True).encode())
        artifact = await store.put(request.review_id + '/review.json',
            json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
    return {'review_id': request.review_id, 'authority': 'suggestion', 'auto_applied': False,
            'summary': report['summary'], 'manifest': manifest.model_dump(mode='json'),
            'artifact': artifact.model_dump(mode='json')}
