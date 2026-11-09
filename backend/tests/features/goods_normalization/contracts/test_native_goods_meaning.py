"""Native meaning and source statements remain distinct in the goods Draft."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
import yaml

from teoria.features.semantic_modeling.ontology.blueprint import OntologyBlueprint
from teoria.features.semantic_modeling.ontology.publication_contracts import (
    PublishedOntologyContext, publication_checksum,
)
from teoria.features.goods_normalization.profiles.compiler import resolve_profile_template, compile_package
from teoria.features.goods_normalization.contracts.specification_graph import (
    DocumentGoodsGraph, validate_graph_meanings,
)
from teoria.features.specification_processing.normalization.profile_application import apply_profile

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def native_context():
    """Deterministic test IDs, not an actual publication or semantic approval."""
    blueprint = OntologyBlueprint.load(ROOT / 'authoring/ontology_blueprints/goods.yaml')
    identifiers = {item.stable_key:str(uuid5(NAMESPACE_URL,item.stable_key)) for item in blueprint.objects}
    objects = []
    for item in blueprint.objects:
        props = [{**prop.model_dump(), 'concept_id':str(uuid5(NAMESPACE_URL,prop.stable_key))}
                 for prop in item.properties]
        identifiers.update({p['stable_key']:p['concept_id'] for p in props})
        objects.append({'concept_id':identifiers[item.stable_key], 'business_object_id':'revision:'+item.code,
                        'stable_key':item.stable_key, 'name':item.name, 'description':item.description,
                        'properties':props})
    relationships = [{**rel.model_dump(), 'concept_id':str(uuid5(NAMESPACE_URL,rel.stable_key)),
                      'source_object_id':'revision:'+rel.source, 'target_object_id':'revision:'+rel.target}
                     for rel in blueprint.relationships]
    content = {'namespace':blueprint.namespace, 'version':blueprint.target_version,
               'objects':objects, 'relationships':relationships, 'rules':[], 'metrics':[]}
    reference = {'version_id':str(uuid4()), 'namespace':blueprint.namespace, 'version':blueprint.target_version,
                 'checksum':publication_checksum(content)}
    context = PublishedOntologyContext.from_publications([{'ontology':reference,'content':content}])
    graph = DocumentGoodsGraph.model_validate(yaml.safe_load(
        (ROOT / 'authoring/specification_examples/server_memory_graph.yaml').read_text())['graphs'][0])
    return context, identifiers, graph


def linked_graph(native_context):
    context, identifiers, source = native_context
    graph = source.model_copy(deep=True)
    reference = context.ontologies[0].ontology
    from teoria.features.semantic_modeling.ontology.publication_contracts import PublishedConceptRef
    for subject in graph.subjects:
        subject.type_concept_ref = PublishedConceptRef(ontology=reference,
            concept_id=identifiers[subject.type_ref.removeprefix('draft:')])
    for prop in graph.properties:
        prop.property_concept_ref = PublishedConceptRef(ontology=reference,
            concept_id=identifiers[prop.characteristic_ref.removeprefix('draft:')])
    return graph


def test_concept_links_validate_ownership_without_replacing_source_observations(native_context):
    context, _, original = native_context
    graph = linked_graph(native_context)
    before = graph.model_copy(deep=True)
    report = validate_graph_meanings(graph, context)
    assert report['linked_subjects'] == 2 and report['linked_properties'] == 3
    assert not report['publication_authority_verified'] and not report['semantic_equivalence_confirmed']
    assert graph == before
    assert [(p.value,p.operator,p.assertion_role,p.evidence_ids) for p in graph.properties] == [
        (p.value,p.operator,p.assertion_role,p.evidence_ids) for p in original.properties]
    assert graph.review_status == 'proposed'


@pytest.mark.parametrize('problem,reason', [('owner','owner_mismatch'), ('kind','kind_mismatch'),
                                          ('version','pinned_publication'), ('unlinked','owner_unresolved')])
def test_wrong_or_unreviewed_concept_references_do_not_resolve_by_name(native_context, problem, reason):
    context, identifiers, _ = native_context
    graph = linked_graph(native_context)
    prop = graph.properties[0]
    if problem == 'owner':
        prop.property_concept_ref.concept_id = identifiers['goods.server.system_memory_capacity']
    elif problem == 'kind':
        prop.property_concept_ref.concept_id = identifiers['goods.memory_module']
    elif problem == 'version':
        prop.property_concept_ref.ontology = prop.property_concept_ref.ontology.model_copy(update={'version_id':uuid4()})
    else:
        next(subject for subject in graph.subjects if subject.subject_id == prop.subject_id).type_concept_ref = None
    with pytest.raises(ValueError, match=reason):
        validate_graph_meanings(graph, context)


def test_unlinked_source_graph_needs_no_definition_dictionary(native_context):
    context, _, graph = native_context
    report = validate_graph_meanings(graph, context)
    assert report['linked_properties'] == report['linked_subjects'] == 0
    assert report['unlinked_properties'] == 3
    assert all(prop.characteristic_ref.startswith('draft:') for prop in graph.properties)


def test_native_profile_keeps_module_capacity_socket_limit_and_slots_distinct(native_context):
    context, identifiers, graph = native_context
    content = context.ontologies[0].content
    template = json.loads((ROOT.parent / 'docs/procurement_specification_processing/examples/server_memory_profile.json').read_text())
    profile = resolve_profile_template(template, content, version_id=context.ontologies[0].ontology.version_id)
    package = compile_package(profile, content, revision_id=uuid4(), approval_actor='fixture:reviewer')
    evidence = {e.evidence_id:e for e in graph.evidence}
    entities = [{'id':s.subject_id,'name':s.name,'kind':'equipment',
                 'evidence':[{'node_id':i} for i in s.evidence_ids]} for s in graph.subjects]
    attrs = [{'id':p.statement_id, 'subject_ids':[p.subject_id],
              'property_key':p.characteristic_ref.rsplit('.',1)[-1], 'data_type':'number',
              'value_raw':str(p.value.number), 'unit_raw':p.value.unit_raw, 'operator':p.operator,
              'operator_raw':None, 'qualifiers_raw':[], 'semantic_scope':p.semantic_scope,
              'semantic_role':'supported_capability' if p.assertion_role == 'supported_capability' else 'requirement_candidate',
              'evidence':{'node_id':p.evidence_ids[0]}} for p in graph.properties]
    corpus = {'classification_code':None,'documents':[{'document_id':graph.document_id,
        'source':{'sha256':graph.source_sha256}, 'entities':entities,'attributes':attrs,
        'relations':[{'id':'components','source_id':'memory','target_id':'server','kind':'component_of',
                      'evidence':[{'node_id':'memory_clause'}]}],
        'parsed_document':{'nodes':[{'node_id':key,'text':e.quote} for key,e in evidence.items()]}}]}
    meaning = {'policy_version':'published_ontology_expression_v2','documents':[{
        'document_id':graph.document_id,
        'entities':[{'id':s.subject_id,'meaning_status':'resolved',
                     'ontology':profile.ontology.model_dump(mode='json'),
                     'ontology_concept_ref':identifiers[s.type_ref.removeprefix('draft:')]} for s in graph.subjects],
        'attributes':[{'id':p.statement_id,'meaning_status':'resolved',
                       'ontology':profile.ontology.model_dump(mode='json'),
                       'ontology_concept_ref':identifiers[p.characteristic_ref.removeprefix('draft:')]} for p in graph.properties]}]}
    before = deepcopy(corpus)
    result, candidates = apply_profile(corpus, package, run_id='controlled_native_test', meaning_alignment=meaning)
    assert corpus == before and profile.classification_code is None
    observations = {p['property_stable_key']:p['semantic_observation'] for p in result['documents'][0]['requirements']}
    assert observations['goods.memory_module.capacity']['value']['decimal'] == '32'
    limit = observations['goods.server.memory_capacity_per_socket_limit']
    assert limit['value_raw'] == '3' and limit['unit_raw'] == 'TB'
    assert limit['value']['decimal'] == '3000' and limit['information_kind'] == 'capability'
    assert limit['scope'] == 'per_socket'
    assert observations['goods.server.memory_slot_count']['value']['decimal'] == '32'
    assert 'goods.server.system_memory_capacity' not in observations  # no invented 32 * 2 total
    assert candidates['bundle']['classification_code'] is None
    different = deepcopy(corpus);different['classification_code'] = '4321150102'
    with pytest.raises(ValueError, match='classification mismatch'):
        apply_profile(different, package, run_id='wrong_scope', meaning_alignment=meaning)
