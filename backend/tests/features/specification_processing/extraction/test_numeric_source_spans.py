"""Numeric observations must cite complete source numbers, including precision and signs."""

import pytest

from teoria.features.specification_processing.extraction.attribute_extraction import (
    decode_batch, narrow_source_evidence, spans,
)


@pytest.mark.parametrize(('text', 'raw', 'expected'), [
    ('48MB', '8', []), ('3.50GHz', '50', []), ('3.50GHz', '3.5', []),
    ('3.264GHz', '64', []),
    ('1,024 MB', '24', []), ('-10℃', '10', []), ('−10℃', '10', []), ('+8 core', '8', []),
    ('3.50GHz', '3.50', [[0, 4]]), ('1,024 MB', '1,024', [[0, 5]]),
    ('-10℃', '-10', [[0, 3]]), ('0-10℃', '10', [[2, 4]]),
    ('８ core', '8', [[0, 1]]), ('⑩개', '10', [[0, 1]]),
    ('8,16 core', '16', [[2, 4]]), ('8개.', '8', [[0, 1]]),
])
def test_complete_numeric_literals_preserve_source_positions(text, raw, expected):
    assert spans(text, raw, complete_number=True) == expected


def test_server_core_evidence_does_not_include_the_digit_inside_cache_capacity():
    # Source server workbook C2: clock, cores, threads and cache share one line.
    text = '3.50GHz 8‑코어 16‑스레드 48MB'
    document = {'nodes': [{'node_id': 'n', 'text': text, 'native_ref': '/cell'}]}
    graph = {'document_id': 'd', 'entities': [{'id': 'item'}]}
    chunk = [{'id': 'f', 'node_id': 'n', 'text': text, 'start': 0, 'end': len(text),
              'suggested_subject_ids': ['item']}]
    fact = ['f', ['item'], 'core_count', None, 'number', 'eq', None, '8', None, []]
    accepted, held, _ = decode_batch({'facts': [fact]}, chunk, graph, document, 0)
    assert not held and len(accepted) == 1
    first = text.index('8‑코어')
    assert accepted[0]['evidence']['field_spans']['value_raw'] == [[first, first + 1]]


def test_incomplete_numeric_predictions_are_quarantined_without_rewriting_values():
    text = '48MB'
    document = {'nodes': [{'node_id': 'n', 'text': text, 'native_ref': '/n'}]}
    graph = {'document_id': 'd', 'entities': [{'id': 'item'}]}
    chunk = [{'id': 'f', 'node_id': 'n', 'text': text, 'start': 0, 'end': len(text),
              'suggested_subject_ids': ['item']}]
    valid = ['f', ['item'], 'capacity', None, 'number', 'eq', None, '48', 'MB', []]
    invalid = [*valid[:7], '8', *valid[8:]]
    accepted, held, _ = decode_batch({'facts': [valid, invalid]}, chunk, graph, document, 0)
    assert [a['value_raw'] for a in accepted] == ['48']
    assert len(held) == 1 and held[0]['raw_prediction'] == invalid


def test_narrowing_a_quote_cannot_move_eight_cores_to_the_eight_inside_48mb():
    text = '8‑코어 / 48MB'
    attribute = {'value_raw': '8', 'data_type': 'number',
                 'evidence': {'node_id': 'n', 'char_start': 0, 'char_end': len(text)}}
    nodes = {'n': {'text': text}}
    with pytest.raises(ValueError, match='value_raw'):
        narrow_source_evidence(attribute, nodes, '48MB')
    evidence = narrow_source_evidence(attribute, nodes, '8‑코어')
    assert evidence['field_spans']['value_raw'] == [[0, 1]]


def test_non_numeric_string_matching_keeps_its_existing_contract():
    assert spans('제품 X48MB', 'X48MB') == [[3, 8]]
    assert spans('폭 800㎜ 이상', '800 mm') == [[2, 6]]


@pytest.mark.parametrize(('quantity','accepted'), [('100',True),('10',False),('1',False)])
def test_inventory_and_automatic_adoption_use_complete_source_numbers(quantity,accepted):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import Inventory,validate_inventory
    from teoria.features.specification_processing.parsing.document_evidence import attribute_is_grounded
    # bioreactor.pdf page 2: original SHA eaad6e7afc080b4c86fa96fb612bbbe84ba9b861e2402d40f2096cca5229e1a3.
    # This isolates numeric grounding; it does not classify a program count as a purchase quantity.
    text='11. 프로그램: 100개 저장'
    nodes=[{'node_id':'n','text':text}]
    inventory=Inventory(root=('n','프로그램',quantity,'개',['n']),basis='technical_sections',
        basis_node_ids=['n'],items=[],integrated_scope=False,scope_evidence_node_ids=[],issues=[])
    assert (not validate_inventory(inventory,{'nodes':nodes}))==accepted
    attribute={'data_type':'number','value_raw':quantity,'unit_raw':'개','evidence':{'node_id':'n'}}
    assert attribute_is_grounded({'parsed_document':{'nodes':nodes}},attribute)==accepted


def test_checkpoint_numeric_failure_identifies_the_observation_without_source_text():
    from types import SimpleNamespace
    from teoria.features.specification_processing.tasks import validate_checkpoint
    from teoria.features.specification_processing.processing_errors import SpecificationProcessingError
    source={'sha256':'a'*64}
    document={'document_id':'doc','source':source,'parsed_document':{'nodes':[{
        'node_id':'n','text':'11. 프로그램: 100개 저장'}]},'entities':[],'relations':[],
        'attributes':[{'id':'attribute_quantity_root','subject_ids':[],'data_type':'number',
                       'value_raw':'10','evidence':{'node_id':'n'}}]}
    corpus={'classification_code':None,'documents':[document],'unavailable_documents':[]}
    with pytest.raises(SpecificationProcessingError) as error:
        validate_checkpoint(corpus,SimpleNamespace(classification_code=None),[{'document_id':'doc','source':source}])
    assert error.value.code=='source_numeric_literal_mismatch'
    assert error.value.details=={'document_id':'doc','attribute_id':'attribute_quantity_root','node_id':'n'}
    assert '프로그램' not in str(error.value)
