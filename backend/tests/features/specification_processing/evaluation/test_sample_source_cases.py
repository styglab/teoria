"""Four known, unclassified originals calibrate the existing grader with controlled errors."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from teoria.features.specification_processing.evaluation_cases import EntityCase,RelationCase,RequirementCase
from teoria.features.specification_processing.evaluation_scoring import score_extraction


FIXTURE=Path(__file__).with_name('fixtures')/'sample_source_cases.json'
CASES=json.loads(FIXTURE.read_text())['documents']


@pytest.fixture(params=CASES,ids=lambda case:case['document_id'])
def source_case(request):
    case=deepcopy(request.param)
    entities={e['id']:e for e in case['entities']}
    names=lambda key:entities[key]['name']
    # Classification is deliberately absent: these are source-case tests, not a
    # sampled server evaluation or a bypass of verify_document's metadata checks.
    expected=SimpleNamespace(
        document_id=case['document_id'],sha256=case['source_sha256'],label_status='silver',entity_aliases={},
        entities=[EntityCase(name=e['name'],source_text=e['name'],owner=names(e['owner']) if e.get('owner') else None) for e in entities.values()],
        relations=[RelationCase(source=names(r['source_id']),target=names(r['target_id']),kind=r['kind'],source_text=r['source_text']) for r in case['relations']],
        requirements=[RequirementCase(subjects=[names(r['subject_id'])],value_raw=r['value_raw'],unit_raw=r['unit_raw'],
            operator=r['operator'],role=r['role'],scope=r['scope'],source_text=r['source_text'],
            owner=names(entities[r['subject_id']]['owner'])) for r in case['requirements']],
    )
    actual={
        'document_id':case['document_id'],'source':{'sha256':case['source_sha256']},'extraction_status':'extracted',
        'parser':{'version':case['parser_version']},'parsed_document':{'nodes':case['source_nodes']},
        'entities':[{'id':e['id'],'name':e['name'],'kind':'equipment','evidence':[{'node_id':e['node_id']}]} for e in entities.values()],
        'relations':[{'source_id':r['source_id'],'target_id':r['target_id'],'kind':r['kind'],
                      'evidence':[{'node_id':key} for key in r['source_node_ids']]} for r in case['relations']],
        'attributes':[{'id':f'a{i}','subject_ids':[r['subject_id']],'property_key':r['property_key'],
            'value_raw':r['value_raw'],'unit_raw':r['unit_raw'],'operator':r['operator'],'operator_raw':r['operator_raw'],
            'qualifiers_raw':[],'semantic_role':r['role'],'semantic_scope':r['scope'],
            'evidence':{'node_id':r['node_id']}} for i,r in enumerate(case['requirements'])],
    }
    return case,expected,actual


def metrics(expected,actual):
    return score_extraction({'documents':[actual]},[expected])['metrics']


def test_source_controls_match_all_frozen_entities_relations_and_requirements(source_case):
    case,expected,actual=source_case
    nodes={n['node_id']:n['text'] for n in case['source_nodes']}
    assert case['classification_code'] is None
    for entity in case['entities']:
        assert entity['name'] in nodes[entity['node_id']]
    for requirement in case['requirements']:
        assert requirement['source_text'] in nodes[requirement['node_id']]
    # Also check ancestry through a third level, not only immediate parents.
    entities={e['id']:e for e in case['entities']}
    for entity,expected_entity in zip(case['entities'],expected.entities):
        parent=entities.get(entity.get('owner'))
        if parent and parent.get('owner'):
            expected_entity.owner=entities[parent['owner']]['name']
    result=metrics(expected,actual)
    for kind in ('entity','relation','requirement'):
        assert result[kind+'_cases_found']==result[kind+'_cases_total']
    assert result['ungrounded_entities']==result['ungrounded_attributes']==result['duplicate_attributes']==0


@pytest.mark.parametrize('failure',['subject','value','unit','operator','role','scope','evidence','qualifier','missing'])
def test_controlled_requirement_errors_are_rejected(source_case,failure):
    _,expected,actual=source_case
    attribute=actual['attributes'][0]
    if failure=='subject':attribute['subject_ids']=[actual['entities'][0]['id']]
    if failure=='value':attribute['value_raw']='원문에 없는 값'
    if failure=='unit':attribute['unit_raw']='원문에 없는 단위'
    if failure=='operator':attribute['operator']='lte' if attribute['operator']!='lte' else 'gte'
    if failure=='role':attribute['semantic_role']='existing_reference'
    if failure=='scope':attribute['semantic_scope']='system_total'
    if failure=='evidence':attribute['evidence']={'node_id':'not_in_source'}
    if failure=='qualifier':attribute['qualifiers_raw']=['모든 장비에 적용한다는 가상의 조건']
    if failure=='missing':actual['attributes']=[]
    result=metrics(expected,actual)
    assert result['requirement_cases_found']==0
    assert result['requirement_cases_total']==len(expected.requirements)


def test_reversed_relations_are_rejected_without_erasing_the_denominator(source_case):
    _,expected,actual=source_case
    for relation in actual['relations']:
        relation['source_id'],relation['target_id']=relation['target_id'],relation['source_id']
    result=metrics(expected,actual)
    assert result['relation_cases_found']==0
    assert result['relation_cases_total']==len(expected.relations)


def test_a_compatible_relationship_cannot_replace_a_component_or_specification_link(source_case):
    _,expected,actual=source_case
    for relation in actual['relations']:relation['kind']='compatible_with'
    assert metrics(expected,actual)['relation_cases_found']==0


def test_missing_parent_link_breaks_requirement_ownership(source_case):
    _,expected,actual=source_case
    actual['relations']=[]
    assert metrics(expected,actual)['requirement_cases_found']==0


def test_same_source_extracted_twice_is_still_a_duplicate(source_case):
    _,expected,actual=source_case
    duplicate=deepcopy(actual['attributes'][0]);duplicate['id']='retry_observation'
    duplicate['evidence']['fragment_id']='retry_fragment'
    actual['attributes'].append(duplicate)
    assert metrics(expected,actual)['duplicate_attributes']==1


def test_failed_document_stays_in_the_denominator(source_case):
    _,expected,_=source_case
    result=score_extraction({'documents':[]},[expected])['metrics']
    assert result['failed_documents']==1
    for kind,cases in [('entity',expected.entities),('relation',expected.relations),('requirement',expected.requirements)]:
        assert result[kind+'_cases_total']==len(cases) and result[kind+'_cases_found']==0


def test_available_originals_still_match_the_frozen_source_hashes():
    root=Path(__file__).resolve().parents[5]/'.artifacts/sample'
    if not all((root/case['source_name']).is_file() for case in CASES):
        pytest.skip('Original samples are local inputs; compact source cases remain available in CI')
    for case in CASES:
        assert hashlib.sha256((root/case['source_name']).read_bytes()).hexdigest()==case['source_sha256']
