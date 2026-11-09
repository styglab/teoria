"""Source-backed silver controls for concise names; not real-model accuracy tests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from teoria.domains.goods.data_processing.evaluation.cases import EntityCase, RelationCase, RequirementCase
from teoria.domains.goods.data_processing.evaluation.scoring import score_extraction


@pytest.mark.parametrize('error', [None, 'missing_alias', 'swapped_subjects', 'merged_subjects', 'operator'])
def test_short_name_does_not_relax_distinct_target_quantity_checks(error):
    case = json.loads((Path(__file__).with_name('fixtures') / 'farm_target_cases.json').read_text())
    expected = SimpleNamespace(
        document_id='farm', sha256=case['sha256'], label_status='silver',
        entity_aliases=case['entity_aliases'], compositions=[], quantities=[],
        entities=[EntityCase(**row) for row in case['entities'][-2:]],
        relations=[RelationCase(**row) for row in case['relations'][-2:]],
        requirements=[RequirementCase(**row) for row in case['requirements'][-2:]],
    )
    names = [row.name for row in expected.entities]
    actual = {
        'document_id': 'farm', 'source': {'sha256': case['sha256']},
        'parsed_document': {'nodes': case['source_nodes']},
        'entities': [
            {'id': 'laser', 'name': expected.entities[0].owner, 'kind': 'equipment', 'evidence': [{'node_id': 'n00125'}]},
            {'id': 'first', 'name': names[0], 'kind': 'equipment', 'evidence': [{'node_id': 'n00136'}]},
            {'id': 'second', 'name': 'Target 또는 반사체', 'kind': 'equipment', 'evidence': [{'node_id': 'n00136'}]},
        ],
        'relations': [
            {'source_id': key, 'target_id': 'laser', 'kind': 'component_of', 'evidence': [{'node_id': 'n00136'}]}
            for key in ('first', 'second')
        ],
        'attributes': [
            {'id': key, 'subject_ids': [key], 'property_key': 'quantity', 'value_raw': row.value_raw,
             'unit_raw': row.unit_raw, 'operator': row.operator, 'operator_raw': '이상',
             'semantic_role': row.role, 'semantic_scope': row.scope, 'evidence': {'node_id': 'n00136'}}
            for key, row in zip(('first', 'second'), expected.requirements)
        ],
    }
    if error == 'missing_alias':
        expected.entity_aliases = {}
    elif error == 'swapped_subjects':
        actual['attributes'][0]['subject_ids'], actual['attributes'][1]['subject_ids'] = ['second'], ['first']
    elif error == 'merged_subjects':
        actual['attributes'][1]['subject_ids'] = ['first']
    elif error == 'operator':
        actual['attributes'][1]['operator'] = 'lte'
    metrics = score_extraction({'documents': [actual]}, [expected])['metrics']
    assert metrics['requirement_cases_total'] == 2
    if error is None:
        assert metrics['entity_cases_found'] == metrics['relation_cases_found'] == metrics['requirement_cases_found'] == 2
        assert metrics['ungrounded_entities'] == metrics['ungrounded_attributes'] == 0
    else:
        assert metrics['requirement_cases_found'] < 2
