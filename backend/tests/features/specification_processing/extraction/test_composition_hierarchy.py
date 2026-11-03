from copy import deepcopy
import pytest

from teoria.features.specification_processing.extraction.composition_hierarchy import composition_hierarchy


def nested_document():
    ids = ['goods', 'system', 'pc', 'cpu', 'chip']
    return {
        'composition_inventory': {'root_id': 'goods', 'basis': 'configuration_list', 'integrated_scope': True,
                                  'item_ids': ['system']},
        'entities': [{'id': key, 'name': key, 'kind': 'equipment'} for key in ids],
        'relations': [{'source_id': child, 'target_id': parent, 'kind': 'component_of',
                       'basis': 'explicit', 'evidence': [{'node_id': 'n'}]}
                      for parent, child in zip(ids, ids[1:])],
        'attributes': [{'subject_ids': ['cpu'], 'value_raw': '8', 'unit_raw': 'core',
                        'evidence': {'node_id': 'n'}}],
        'declared_quantities': [{'entity_id': 'cpu', 'value_raw': '2', 'unit_raw': '개'}],
    }


@pytest.mark.parametrize('names',[
    ['서버', '데이터 처리 시스템', 'PC SYSTEM', 'CPU', '칩'],
    ['포장 설비', '충전 장치', '펌프 모듈', '구동부', '베어링'],
])
def test_primary_composition_has_three_levels_and_keeps_all_deeper_observations(names):
    document = nested_document()
    # Renaming every ID and label must not change the depth policy.
    ids={e['id']:f'target_{i}' for i,e in enumerate(document['entities'])}
    for e,name in zip(document['entities'],names):e.update(id=ids[e['id']],name=name)
    for r in document['relations']:
        for key in ('source_id','target_id'):r[key]=ids[r[key]]
    document['composition_inventory'].update(root_id='target_0',item_ids=['target_1'])
    document['attributes'][0]['subject_ids']=['target_3']
    document['declared_quantities'][0]['entity_id']='target_3'
    before = deepcopy(document)
    hierarchy = composition_hierarchy(document)
    assert hierarchy['root_ids'] == ['target_0']
    assert hierarchy['primary_entity_ids'] == ['target_0', 'target_1', 'target_2']
    assert hierarchy['detail_entity_ids'] == ['target_3', 'target_4']
    assert hierarchy['levels'] == {f'target_{i}':i+1 for i in range(5)}
    assert document == before  # No reparenting, attribute conversion, quantity propagation or evidence loss.


def test_independent_purchase_roots_each_start_at_level_one():
    document = nested_document()
    document['entities'].append({'id': 'milk', 'kind': 'product', 'document_roles': ['supply_target']})
    hierarchy = composition_hierarchy(document)
    assert hierarchy['root_ids'] == ['goods', 'milk']
    assert hierarchy['levels']['milk'] == 1


def test_held_parent_is_not_promoted_into_primary_or_deep_composition():
    document = nested_document()
    document['held_relations'] = [document['relations'].pop(1)]
    hierarchy = composition_hierarchy(document)
    assert hierarchy['primary_entity_ids'] == ['goods', 'system']
    assert hierarchy['detail_entity_ids'] == []
    assert 'pc' not in hierarchy['levels']


def test_multiple_parent_and_cycle_do_not_create_invented_levels():
    document = nested_document()
    document['relations'].append({**document['relations'][1], 'target_id': 'chip'})
    hierarchy = composition_hierarchy(document)
    assert hierarchy['primary_entity_ids'] == ['goods', 'system']
    assert hierarchy['detail_entity_ids'] == []


def test_existing_equipment_branch_is_not_primary_purchase_composition():
    document = nested_document()
    document['entities'][1]['document_roles'] = ['existing_target']
    hierarchy = composition_hierarchy(document)
    assert hierarchy['primary_entity_ids'] == ['goods']
    assert hierarchy['detail_entity_ids'] == []
