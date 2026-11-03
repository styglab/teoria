from copy import deepcopy

import pytest

from teoria.features.specification_processing.extraction.inline_attribute_units import recover_inline_attribute_units
from teoria.features.specification_processing.parsing.document_evidence import attribute_is_grounded


def observation(text, value, *, span=None):
    document = {'nodes': [{'node_id': 'n', 'text': text}]}
    attribute = {'subject_ids': ['target'], 'property_key': 'source_measurement', 'data_type': 'number',
                 'semantic_role': 'requirement_candidate', 'operator': 'eq', 'value_raw': value,
                 'unit_raw': None, 'qualifiers_raw': [],
                 'evidence': {'node_id': 'n', 'char_start': 0, 'char_end': len(text), 'quote': text}}
    if span is not None:
        attribute['evidence']['field_spans'] = {'value_raw': [span]}
    return document, attribute


@pytest.mark.parametrize(('text', 'value', 'unit', 'normalized'), [
    ('8‑코어', '8', '코어', 'core'), ('16‑스레드', '16', '스레드', 'thread'),
    ('압력 105 MPa', '105', 'MPa', 'MPa'), ('용량 32GB', '32', 'GB', 'GB'),
    ('속도 2.5 mL/min', '2.5', 'mL/min', 'mL/min'),
])
def test_recovers_literal_adjacent_units_without_using_target_names(text, value, unit, normalized):
    document, attribute = observation(text, value)
    original = deepcopy(attribute)
    assert recover_inline_attribute_units(document, [attribute])['unit_recoveries'] == 1
    assert attribute['unit_raw'] == unit
    assert attribute['normalized']['unit'] == normalized
    for key in ('subject_ids', 'value_raw', 'operator', 'property_key', 'qualifiers_raw'):
        assert attribute[key] == original[key]
    a, b = attribute['evidence']['field_spans']['unit_raw'][0]
    assert text[a:b] == unit
    assert attribute_is_grounded({'parsed_document': document}, attribute)
    once = deepcopy(attribute)
    assert recover_inline_attribute_units(document, [attribute])['unit_recoveries'] == 0
    assert attribute == once


def test_uses_the_exact_value_span_in_a_cell_with_repeated_numbers():
    text = '메모리 32GB, 주파수 32MHz'
    start = text.rindex('32')
    document, attribute = observation(text, '32', span=[start, start + 2])
    recover_inline_attribute_units(document, [attribute])
    assert attribute['unit_raw'] == 'MHz'
    document, ambiguous = observation(text, '32')
    assert recover_inline_attribute_units(document, [ambiguous])['ambiguous_values'] == 1
    assert ambiguous['unit_raw'] is None


def test_extends_a_numeric_quote_only_to_include_its_adjacent_unit():
    document, attribute = observation('8‑코어 / 16‑스레드', '8', span=[0, 1])
    attribute['evidence'].update(char_end=1, quote='8')
    recover_inline_attribute_units(document, [attribute])
    assert attribute['evidence']['quote'] == '8‑코어'
    assert attribute_is_grounded({'parsed_document': document}, attribute)


@pytest.mark.parametrize('text', ['8\n코어', '8 GHz/s', '8 GBextra', '8 DIMM', '8개를 제공', '8, 주파수 GHz'])
def test_does_not_search_other_clauses_or_accept_partial_unit_tokens(text):
    document, attribute = observation(text, '8')
    before = deepcopy(attribute)
    assert recover_inline_attribute_units(document, [attribute])['unit_recoveries'] == 0
    assert attribute == before


@pytest.mark.parametrize('change', ['existing_unit', 'identifier', 'unknown_role', 'wrong_span'])
def test_does_not_rewrite_existing_units_identifiers_or_unverified_observations(change):
    document, attribute = observation('8‑코어', '8', span=[0, 1])
    if change == 'existing_unit': attribute['unit_raw'] = 'core'
    elif change == 'identifier': attribute['data_type'] = 'identifier'
    elif change == 'unknown_role': attribute['semantic_role'] = 'unknown'
    else: attribute['evidence']['field_spans']['value_raw'] = [[1, 2]]
    before = deepcopy(attribute)
    assert recover_inline_attribute_units(document, [attribute])['unit_recoveries'] == 0
    assert attribute == before
