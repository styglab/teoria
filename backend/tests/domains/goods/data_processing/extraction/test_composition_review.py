"""Composition review must not turn capabilities, existing assets, or services into supplied parts."""
from copy import deepcopy

import pytest

from teoria.domains.goods.data_processing.extraction.attribute_resolution import resolve_attribute_semantics
from teoria.domains.goods.data_processing.extraction.composition_review import add_composition_links


def example():
    text = '컴퓨터 서버 구성: CPU 64Core/128Thread processor. 기존 서버 내 부품 장착 작업 수행.'
    document = {'nodes': [{'node_id': 'n', 'kind': 'paragraph', 'text': text, 'native_ref': '/blocks/18'}]}
    graph = {'entities': [
        {'id': 'root', 'name': '컴퓨터 서버', 'kind': 'equipment'},
        {'id': 'cpu', 'name': 'CPU', 'kind': 'equipment'},
        {'id': 'existing', 'name': '기존 서버', 'kind': 'equipment', 'document_roles': ['existing_target']},
        {'id': 'install', 'name': '부품 장착 작업', 'kind': 'activity'},
    ], 'relations': [{'id': 'service', 'source_id': 'install', 'target_id': 'existing',
                       'kind': 'service_for', 'basis': 'explicit', 'evidence': [{'node_id': 'n'}]}],
        'requirements': [{'text': text}],
        'attributes': [{'id': 'a', 'subject_ids': ['cpu'], 'value_raw': '64', 'unit_raw': 'Core',
                        'property_key': 'core_count', 'data_type': 'number', 'operator': 'eq',
                        'evidence': {'node_id': 'n'}, 'semantic_role': 'requirement_candidate',
                        'semantic_scope': 'per_processor'}]}
    link = {'source_id': 'cpu', 'target_id': 'root', 'kind': 'component_of',
            'attribute_ids': ['a'], 'evidence': [['n', '컴퓨터 서버 구성: CPU 64Core/128Thread processor.']]}
    return document, graph, link


def test_grounded_composition_preserves_values_and_installation_support():
    document, graph, link = example()
    before = deepcopy(graph)
    result = add_composition_links(graph, document, [link, link])
    assert result == {'added': 1, 'rejected': 0}
    assert graph['relations'][0] == before['relations'][0]
    assert graph['attributes'] == before['attributes']
    assert graph['requirements'] == before['requirements']
    assert graph['relations'][-1]['review_attribute_ids'] == ['a']


def test_attribute_review_cannot_add_a_shortcut_past_the_frozen_inventory():
    document,graph,link=example()
    graph['composition_inventory']={'root_id':'root','basis':'configuration_list',
        'integrated_scope':True,'item_ids':['assembly']}
    graph['entities'].append({'id':'assembly','name':'제공 조립체','kind':'equipment'})
    before=deepcopy(graph)
    assert add_composition_links(graph,document,[link])=={'added':0,'rejected':1}
    assert graph==before


@pytest.mark.parametrize('defect', ['existing', 'capability', 'unknown_owner', 'fabricated_quote',
                                    'unknown_node', 'service', 'cycle', 'contents', 'missing_attribute'])
def test_unsupported_composition_is_not_added(defect):
    document, graph, link = example()
    if defect == 'existing': link['target_id'] = 'existing'
    if defect == 'capability': graph['attributes'][0]['semantic_role'] = 'supported_capability'
    if defect == 'unknown_owner': graph['attributes'][0]['subject_ids'] = []
    if defect == 'fabricated_quote': link['evidence'][0][1] = 'CPU 128개 제공'
    if defect == 'unknown_node': link['evidence'][0][0] = 'absent'
    if defect == 'service': link['source_id'] = 'install'
    if defect == 'cycle':
        graph['relations'].append({'id': 'reverse', 'source_id': 'root', 'target_id': 'cpu',
                                   'kind': 'component_of', 'basis': 'explicit', 'evidence': [{'node_id': 'n'}]})
    if defect == 'contents': document['document_assessment'] = {'node_roles': {'n': 'table_of_contents'}}
    if defect == 'missing_attribute': link['attribute_ids'] = ['absent']
    before = deepcopy(graph)
    assert add_composition_links(graph, document, [link]) == {'added': 0, 'rejected': 1}
    assert graph == before


async def test_existing_ownership_call_also_reviews_composition_without_an_extra_call(tmp_path):
    document, graph, link = example()
    class Runner:
        calls = 0
        async def generate(self, prompt, request, out):
            self.calls += 1
            return {'resolutions': [{'attribute_id': 'a', 'subject_ids': ['cpu'],
                                     'role': 'requirement_candidate', 'scope': 'per_processor',
                                     'evidence_node_ids': ['n']}], 'composition_links': [link]}
    runner = Runner()
    result = await resolve_attribute_semantics(document, graph, graph['attributes'], runner, tmp_path)
    assert runner.calls == 1
    assert result['composition_review']['added'] == 1
    assert graph['relations'][0]['kind'] == 'service_for'
