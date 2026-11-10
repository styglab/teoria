"""Document-specific approved interpretations; source observations stay immutable."""
from copy import deepcopy
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from teoria.domains.goods.contracts import Record, StandardReference
from teoria.domains.goods.normalization.application.profile_application import apply_profile, observation_id
from teoria.domains.goods.normalization.contracts import NormalizationPackage, checksum
from teoria.domains.goods.normalization.meaning_proposals.meaning_review import (
    EntityMeaningProposal, PropertyMeaningProposal, MeaningReviewInput, build_meaning_review, _evidence_error,
)
from teoria.domains.goods.data_processing.parsing.document_evidence import EvidenceQuote, attribute_is_grounded
from teoria.domains.goods.data_processing.extraction.value_normalization import number
from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology, OntologyPublicationRef
from teoria.platform.ontology.authoring.review_contracts import OntologyReviewSnapshot


class CompositionMeaningProposal(Record):
    relation_id: str = Field(min_length=1)
    quantity_observation_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    child_id: str = Field(min_length=1)
    composition_concept_id: UUID
    quantity_property_concept_id: UUID
    relation_kind: Literal['physical_component', 'system_member', 'accessory']
    inclusion_role: Literal['required', 'optional', 'excluded']
    scope: str = Field(min_length=1, max_length=200)
    evidence: list[EvidenceQuote] = Field(min_length=1)
    rationale: str = Field(min_length=10, max_length=2000)


class InterpretationRequest(Record):
    schema_version: Literal[1] = 1
    review_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    document_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    result: StandardReference
    profile_revision_id: UUID
    entities: list[EntityMeaningProposal] = Field(min_length=1, max_length=100)
    properties: list[PropertyMeaningProposal] = Field(default_factory=list, max_length=500)
    compositions: list[CompositionMeaningProposal] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def distinct_selections(self):
        entity_ids = [e.subject_id for e in self.entities]
        property_ids = [p.observation_id for p in self.properties]
        quantity_ids = [c.quantity_observation_id for c in self.compositions]
        relation_ids = [c.relation_id for c in self.compositions]
        if not (property_ids or quantity_ids):
            raise ValueError('interpretation_selection_required')
        for ids in [entity_ids, property_ids + quantity_ids, relation_ids]:
            if len(ids) != len(set(ids)):
                raise ValueError('duplicate_interpretation_selection')
        return self


class ApprovedInterpretation(Record):
    artifact_kind: Literal['goods_approved_interpretation'] = 'goods_approved_interpretation'
    revision_id: UUID
    status: Literal['approved'] = 'approved'
    approval_actor: str = Field(min_length=1)
    request: InterpretationRequest
    package_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    ontology: OntologyPublicationRef
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def verify_checksum(self):
        if checksum(self.model_dump(mode='json', exclude={'checksum'})) != self.checksum:
            raise ValueError('interpretation_approval_checksum_mismatch')
        return self


def validate_interpretation(request, result, package, publication):
    """Recheck source evidence, publication ownership and the exact profile policy."""
    request = InterpretationRequest.model_validate(request)
    package = NormalizationPackage.model_validate(package)
    publication = PublishedOntology.model_validate(publication)
    if package.profile_revision_id != request.profile_revision_id or package.profile.ontology != publication.ontology:
        raise ValueError('interpretation_profile_or_publication_mismatch')
    content = {**publication.content, 'ontology_version_id': str(publication.ontology.version_id), 'status': 'published'}
    context = dict(version_id=publication.ontology.version_id, namespace=publication.ontology.namespace,
                   version=publication.ontology.version, status='published', content_checksum=checksum(content))
    snapshot = OntologyReviewSnapshot(context=context, content=content)
    # The old review CLI still supports Draft proposals. This path is publication-only.
    review_request = MeaningReviewInput.model_construct(
        schema_version=1, review_id=request.review_id, document_id=request.document_id,
        source_sha256=request.source_sha256, result=request.result, ontology=snapshot.context,
        entities=request.entities, properties=request.properties)
    report = build_meaning_review(review_request, result, snapshot)
    if report['summary']['held']:
        raise ValueError('interpretation_contains_held_proposals')
    document = next(d for d in result['extracted']['documents'] if d['document_id'] == request.document_id)
    classification = document.get('classification_code') or result.get('normalization', {}).get('classification_code')
    if classification != package.profile.classification_code:
        raise ValueError('interpretation_classification_mismatch')
    source_entities = {e['id'] for e in document['entities']}
    if any(not set(a['subject_ids']) <= source_entities for a in document['attributes']):
        raise ValueError('interpretation_source_subject_missing')
    entities = {e.subject_id: str(e.concept_id) for e in request.entities}
    catalog = snapshot.concept_catalog()
    attributes = {a['id']: a for a in document['attributes']}
    relations = {r['id']: r for r in document.get('relations', [])}
    if len(relations) != len(document.get('relations', [])):
        raise ValueError('duplicate_source_relation')
    for proposal in request.compositions:
        relation = relations.get(proposal.relation_id)
        quantity = attributes.get(proposal.quantity_observation_id)
        concept = catalog.get(str(proposal.composition_concept_id))
        prop = catalog.get(str(proposal.quantity_property_concept_id))
        if (relation is None or quantity is None or proposal.parent_id == proposal.child_id
                or proposal.parent_id not in entities or proposal.child_id not in entities
                or relation.get('kind') != 'component_of'
                or (relation['source_id'], relation['target_id']) != (proposal.child_id, proposal.parent_id)
                or quantity['subject_ids'] != [proposal.child_id]
                or quantity.get('property_key') != 'quantity'
                or quantity.get('semantic_role') != 'requirement_candidate'
                or quantity.get('operator') not in {'eq', 'gte', 'lte', 'gt', 'lt'}):
            raise ValueError('interpretation_composition_source_mismatch')
        for observation in [relation, quantity]:
            if _evidence_error(proposal.evidence, document, observation):
                raise ValueError('interpretation_composition_evidence_mismatch')
        raw = number(quantity['value_raw']) if quantity['data_type'] == 'number' else None
        if raw is None or Decimal(raw) < 0 or not attribute_is_grounded(document, quantity):
            raise ValueError('interpretation_quantity_not_grounded')
        if (concept is None or concept['kind'] != 'object'
                or concept['stable_key'] != 'goods.composition_statement'
                or prop is None or prop['kind'] != 'property'
                or prop['stable_key'] != 'goods.composition_statement.quantity_value'
                or prop['owner_concept_id'] != str(proposal.composition_concept_id)
                or prop['value_type'] != 'decimal' or not quantity.get('unit_raw')):
            raise ValueError('interpretation_composition_concept_mismatch')
    adjacency = {}
    for proposal in request.compositions:
        if proposal.inclusion_role != 'excluded':
            adjacency.setdefault(proposal.parent_id, []).append(proposal.child_id)
    visited, visiting = set(), set()
    def visit(subject):
        if subject in visiting:
            raise ValueError('cyclic_interpreted_composition')
        if subject in visited:
            return
        visiting.add(subject)
        for child in adjacency.get(subject, []):
            visit(child)
        visiting.remove(subject)
        visited.add(subject)
    for subject in adjacency:
        visit(subject)
    return document


def apply_interpretation(approval, result, package, publication, *, run_id):
    """Approval authority is established by the Admin export endpoint, not its checksum."""
    approval = ApprovedInterpretation.model_validate(
        approval.model_dump(mode='json') if isinstance(approval, ApprovedInterpretation) else approval)
    request = approval.request
    package = NormalizationPackage.model_validate(package)
    publication = PublishedOntology.model_validate(publication)
    if approval.package_checksum != package.checksum or approval.ontology != publication.ontology:
        raise ValueError('interpretation_approval_context_mismatch')
    document = validate_interpretation(request, result, package, publication)
    original_attributes = {a['id']: a for a in document['attributes']}
    virtual = deepcopy(document)
    selected = {p.observation_id: p for p in request.properties}
    virtual['attributes'] = [a for a in virtual['attributes'] if a['id'] in selected]
    virtual['entities'] = [e for e in virtual['entities'] if e['id'] in {p.subject_id for p in request.entities}]
    virtual['relations'] = []
    for attribute in virtual['attributes']:
        proposal = selected[attribute['id']]
        attribute['subject_ids'] = [proposal.subject_id]
        attribute['semantic_scope'] = proposal.semantic_scope
    reference = publication.ontology.model_dump(mode='json')
    meanings = {'policy_version': 'published_ontology_expression_v2', 'documents': [{
        'document_id': document['document_id'],
        'entities': [{'id': p.subject_id, 'meaning_status': 'resolved', 'ontology': reference,
                      'ontology_concept_ref': str(p.concept_id)} for p in request.entities],
        'attributes': [{'id': p.observation_id, 'meaning_status': 'resolved', 'ontology': reference,
                        'ontology_concept_ref': str(p.concept_id)} for p in request.properties]}]}
    normalized, _ = apply_profile({'classification_code': package.profile.classification_code, 'documents': [virtual]},
                                  package, run_id=run_id, meaning_alignment=meanings)
    applied = normalized['documents'][0]
    if normalized['unresolved_observations'] or len(applied['requirements']) != len(request.properties):
        raise ValueError('interpretation_not_supported_by_approved_profile')
    provenance = {'revision_id': str(approval.revision_id), 'checksum': approval.checksum,
                  'approval_actor': approval.approval_actor, 'request_checksum': checksum(request)}
    observations = []
    for fact in applied['requirements']:
        observation = fact['semantic_observation']
        original = original_attributes[observation['source']['attribute_id']]
        source = observation['source']
        for field in ['expression_snapshot_checksum', 'property_connection', 'subject_connections']:
            source.pop(field, None)
        source.update(approved_interpretation=provenance, original_subject_ids=original['subject_ids'],
                      original_scope=original.get('semantic_scope', 'unknown'), original_role=original.get('semantic_role'),
                      review_evidence=[e.model_dump(mode='json') for e in selected[original['id']].evidence])
        observations.append(observation)
    compositions = []
    source_entities = {e['id']: e for e in document['entities']}
    source_relations = {r['id']: r for r in document.get('relations', [])}
    entity_ids = {e['source_entity_id']: e['observation_id'] for e in applied['entities']}
    for proposal in request.compositions:
        quantity = original_attributes[proposal.quantity_observation_id]
        compositions.append({'composition_id': observation_id(document, run_id, 'composition', proposal.relation_id),
            'ontology': reference, 'composition_concept_id': str(proposal.composition_concept_id),
            'quantity_property_concept_id': str(proposal.quantity_property_concept_id),
            'parent_ref': entity_ids[proposal.parent_id], 'child_ref': entity_ids[proposal.child_id],
            'relation_kind': proposal.relation_kind, 'inclusion_role': proposal.inclusion_role,
            'quantity': {'value': number(quantity['value_raw']), 'value_raw': quantity['value_raw'],
                         'unit_raw': quantity['unit_raw'], 'operator': quantity['operator'], 'scope': proposal.scope},
            'evidence': [e.model_dump(mode='json') for e in proposal.evidence],
            'source_relation_id': proposal.relation_id, 'source_quantity_observation_id': proposal.quantity_observation_id,
            'source': {'document_id': request.document_id, 'source_sha256': request.source_sha256,
                       'approved_interpretation': provenance, 'original_subject_ids': quantity['subject_ids'],
                       'original_scope': quantity.get('semantic_scope', 'unknown'),
                       'original_delivery_status': source_entities[proposal.child_id].get('delivery_status'),
                       'original_relation_review_status': source_relations[proposal.relation_id].get('review_status')}})
    return {'artifact_kind': 'goods_interpretation_application', 'authority': 'approved_interpretation',
            'run_id': run_id, 'document_id': request.document_id, 'source_sha256': request.source_sha256,
            'source_result': request.result.model_dump(mode='json'), 'approval': provenance,
            'entities': applied['entities'], 'observations': observations, 'compositions': compositions,
            'source_observations_unchanged': True}


def merge_interpretations(normalized, applications, package):
    """Merge reviewed projections into a new result; preserve each original extraction separately."""
    from collections import Counter
    result = deepcopy(normalized)
    selected = set()
    concepts = {str(c.concept_id): c for c in package.concepts}
    for application in applications:
        doc_id = application['document_id']
        document = next(d for d in result['documents'] if d['document_id'] == doc_id)
        entities = {e['observation_id']: e for e in document['entities']}
        for entity in application['entities']:
            old = entities.get(entity['observation_id'])
            if old and old.get('status') == 'applied' and old.get('concept_id') != entity['concept_id']:
                raise ValueError('interpretation_entity_mapping_conflict')
            entities[entity['observation_id']] = entity
        document['entities'] = list(entities.values())
        facts = []
        for observation in application['observations']:
            source = observation['source']; identifier = source['attribute_id']
            fact = {'observation_id': observation['observation_id'], 'property_concept_id': observation['concept_id'],
                'property_stable_key': concepts[observation['concept_id']].stable_key,
                'subject_observation_ids': observation['subject_refs'], 'rule_id': source['rule_id'],
                'operator': observation['operator'], 'role': source['original_role'],
                'semantic_scope': observation['scope'], 'value': observation['value'],
                'value_raw': observation['value_raw'], 'unit_raw': observation['unit_raw'],
                'evidence': source['evidence'], 'evidence_ref': doc_id + ':' + identifier,
                'semantic_observation': observation}
            facts.append(fact)
            key = (doc_id, identifier)
            if key in selected:
                raise ValueError('overlapping_interpretation_selections')
            selected.add(key)
            row = next(r for r in result['attributes'] if (r['document_id'],r['attribute_id']) == key)
            row.clear();row.update(document_id=doc_id, attribute_id=identifier, status='applied', facts=[fact])
        for composition in application['compositions']:
            identifier = composition['source_quantity_observation_id'];key = (doc_id,identifier)
            if key in selected:
                raise ValueError('overlapping_interpretation_selections')
            selected.add(key)
            row = next(r for r in result['attributes'] if (r['document_id'],r['attribute_id']) == key)
            row.clear();row.update(document_id=doc_id,attribute_id=identifier,status='applied_composition',
                                   composition_id=composition['composition_id'])
        document['requirements'] = [f for f in document['requirements']
            if (doc_id, f['evidence_ref'].split(':',1)[1]) not in selected] + facts
        document.setdefault('compositions', []).extend(application['compositions'])
        result['unresolved_observations'] = [c for c in result['unresolved_observations']
            if not ((c.get('document_id'),c.get('attribute_id')) in selected
                or (c.get('kind')=='entity' and c.get('observation_id') in entities
                    and entities[c['observation_id']]['status']=='applied')
                or (c.get('document_id')==doc_id and any(c.get('source_relation_id')==v['source_relation_id']
                    for v in application['compositions'])))]
    result['summary'] = dict(Counter(r['status'] for r in result['attributes']))
    result['entity_summary'] = dict(Counter(e['status'] for d in result['documents'] for e in d['entities']))
    result['relation_summary'] = {'applied': sum(len(d['relations']) + len(d.get('compositions', [])) for d in result['documents']),
        'automatically_deferred': sum(c['kind']=='relation' for c in result['unresolved_observations'])}
    return result
