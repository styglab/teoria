"""Source-confirmed model aliases must preserve strict component ownership checks."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from teoria.domains.goods.data_processing.evaluation.cases import EvaluationDocument
from teoria.domains.goods.data_processing.evaluation.scoring import score_extraction


def server_case():
    fixture = json.loads((Path(__file__).parent / 'fixtures/server_component_cases.json').read_text())
    expected = EvaluationDocument.model_validate(fixture['documents'][0])
    cpu = 'Intel Xeon Processor 6507P'
    expected.entities = [case for case in expected.entities if case.name == cpu]
    expected.requirements = expected.requirements[:1]
    full_name = expected.entity_aliases[cpu][0]
    root = '대형언어모델 추론실험용 서버'
    actual = {
        'document_id': expected.document_id,
        'source': {'sha256': expected.sha256},
        'entities': [
            {'id': 'root', 'name': root, 'kind': 'equipment', 'evidence': [{'node_id': 'root'}]},
            {'id': 'cpu', 'name': full_name, 'kind': 'equipment', 'evidence': [{'node_id': 'cpu'}]},
        ],
        'relations': [{'source_id': 'cpu', 'target_id': 'root', 'kind': 'component_of',
                       'evidence': [{'node_id': 'cpu'}]}],
        'attributes': [{'id': 'frequency', 'subject_ids': ['cpu'], 'property_key': 'clock_frequency',
                        'value_raw': '3.50', 'unit_raw': 'GHz', 'operator': 'eq',
                        'semantic_scope': 'per_processor', 'evidence': {'node_id': 'cpu'}}],
        'parsed_document': {'nodes': [{'node_id': 'root', 'text': root},
                                     {'node_id': 'cpu', 'text': full_name}]},
    }
    return expected, actual


def test_source_confirmed_model_alias_matches_relationship_and_property():
    expected, actual = server_case()
    metrics = score_extraction({'documents': [actual]}, [expected])['metrics']
    assert metrics['entity_cases_found'] == 1
    assert metrics['relation_cases_found'] == 1
    assert metrics['requirement_cases_found'] == 1
    # Without the explicitly reviewed alias this remains an exact-name mismatch.
    expected.entity_aliases = {}
    metrics = score_extraction({'documents': [actual]}, [expected])['metrics']
    assert metrics['entity_cases_found'] == metrics['relation_cases_found'] == metrics['requirement_cases_found'] == 0


@pytest.mark.parametrize('change', ['owner', 'unit', 'value', 'direction', 'unreviewed_name'])
def test_alias_does_not_relax_owner_value_unit_or_relationship_direction(change):
    expected, actual = server_case()
    actual = deepcopy(actual)
    if change == 'owner':
        actual['attributes'][0]['subject_ids'] = ['root']
    elif change == 'unit':
        actual['attributes'][0]['unit_raw'] = 'MHz'
    elif change == 'value':
        actual['attributes'][0]['value_raw'] = '3.60'
    elif change == 'direction':
        actual['relations'][0].update(source_id='root', target_id='cpu')
    else:
        name = 'Intel Xeon Processor 6508P 3.50GHz'
        actual['entities'][1]['name'] = name
        actual['parsed_document']['nodes'][1]['text'] = name
    metrics = score_extraction({'documents': [actual]}, [expected])['metrics']
    if change == 'direction':
        assert metrics['relation_cases_found'] == 0
    else:
        assert metrics['requirement_cases_found'] == 0
