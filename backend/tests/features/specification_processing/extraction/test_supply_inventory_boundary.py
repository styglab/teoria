"""Supply-table scope must not be replaced by a work section's overlapping grouping."""
from copy import deepcopy

import pytest

from teoria.features.specification_processing.extraction.entity_relation_extraction import (
    Details, Inventory, materialize, review_relations,
)
from teoria.features.specification_processing.extraction.composition_review import add_composition_links


def supply_and_work_case():
    # Source excerpts from the redox sample; no gas/device equivalence is asserted.
    texts = {
        'root': '환경감시 및 제어 모니터링 장치',
        'list': '공급 목록', 'sensor': '센서 및 분석장치', 'sender': '데이터 전송장치',
        'job': '환경감시 센서 교체 및 설치공사',
        'detail': '환경가스 측정 장치',
        'work': '환경감시 센서의 구성은 누출가스검출기, 혼합가스검출기, 온습도센서, 데이터 전송장치로 구성',
    }
    document = {'document_id': 'supply_work', 'nodes': [
        {'node_id': id, 'text': text, 'native_ref': '/' + id, 'kind': 'paragraph'}
        for id, text in texts.items()]}
    inventory = Inventory(root=('root', texts['root'], None, None, ['root']),
        basis='supply_list', basis_node_ids=['list'], integrated_scope=True,
        scope_evidence_node_ids=['root'], issues=[], items=[
            ('i1', 'sensor', texts['sensor'], None, None, ['sensor']),
            ('i2', 'sender', texts['sender'], None, None, ['sender']),
            ('i3', 'job', texts['job'], None, None, ['job']),
        ])
    details = Details(additional=[('detail', 'detail', texts['detail']),
        ('work', 'work', '환경감시 센서'), ('probe', 'work', '온습도센서')],
        types=[('root', 'equipment', 'required'), ('i1', 'equipment', 'required'),
               ('i2', 'equipment', 'required'), ('i3', 'activity', 'required'),
               ('detail', 'equipment', 'required'), ('work', 'group', 'required'),
               ('probe', 'equipment', 'required')],
        relations=[('detail', 'i1', 'component_of', 'interpreted', ['sensor', 'detail']),
                   ('work', 'root', 'component_of', 'interpreted', ['job', 'work']),
                   ('i2', 'work', 'component_of', 'explicit', ['work']),
                   ('probe', 'work', 'component_of', 'explicit', ['work']),
                   ('i3', 'work', 'service_for', 'explicit', ['job', 'work'])],
        scopes=[('work', ['work']), ('detail', ['detail'])], issues=[])
    return document, inventory, details


@pytest.mark.parametrize('integrated', [True, False])
def test_supply_rows_and_quantities_do_not_restrict_grounded_composition(integrated):
    doc, inventory, details = supply_and_work_case(); inventory.integrated_scope = integrated
    before = deepcopy(details)
    reviewed, held = review_relations(details, inventory, doc)
    assert held == []
    assert any(r[:2] == ('work', 'root') for r in reviewed.relations)
    assert any(r[:2] == ('i2', 'work') for r in reviewed.relations)
    assert reviewed.scopes == before.scopes
    assert any(r[:2] == ('detail', 'i1') for r in reviewed.relations)
    assert any(r[:2] == ('probe', 'work') for r in reviewed.relations)
    graph = materialize(inventory, reviewed, doc, held)
    assert graph['inventory_ids'] == ['i1', 'i2', 'i3']
    assert [r['source_id'] for r in graph['relations'] if r['kind'] == 'in_procurement_scope'] == ['i1', 'i2', 'i3']
    entities = {e['id']: e for e in graph['entities']}
    assert 'work_scope_target' in entities['work']['document_roles']
    assert 'supply_target' in entities['i2']['document_roles']
    assert entities['work']['name'] == '환경감시 센서'
    assert any(q['subject_ids'] == ['work'] for q in graph['requirements'])


def test_group_with_grounded_supply_parent_is_not_work_only():
    doc, inventory, details = supply_and_work_case()
    details.relations = [r for r in details.relations if r[:2] != ('work', 'root')]
    details.relations.append(('work', 'i1', 'component_of', 'explicit', ['sensor', 'work']))
    reviewed, held = review_relations(details, inventory, doc)
    graph = materialize(inventory, reviewed, doc, held)
    assert 'work_scope_target' not in next(e for e in graph['entities'] if e['id'] == 'work')['document_roles']


def test_attribute_review_can_preserve_a_grounded_supply_scope_link():
    doc, inventory, details = supply_and_work_case()
    reviewed, held = review_relations(details, inventory, doc)
    reviewed.relations=[r for r in reviewed.relations if r[:2]!=('i2','work')]
    graph = materialize(inventory, reviewed, doc, held)
    attrs = [{'id': 'a', 'subject_ids': ['i2'], 'semantic_role': 'requirement_candidate', 'semantic_scope': 'this_target'}]
    result = add_composition_links(graph, doc, [{
        'source_id': 'i2', 'target_id': 'work', 'kind': 'component_of',
        'attribute_ids': ['a'], 'evidence': [('work', '데이터 전송장치')],
    }], attrs)
    assert result == {'added': 1, 'rejected': 0}
