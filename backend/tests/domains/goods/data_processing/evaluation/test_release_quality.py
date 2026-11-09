from copy import deepcopy
import pytest
from teoria.domains.goods.data_processing.evaluation.release_quality import check_release_quality
from teoria.domains.goods.data_processing.evaluation.scoring import CASE_NAMES, ERROR_NAMES


def completed():
    metrics = {name: 0 for name in ERROR_NAMES}
    for name in CASE_NAMES:
        metrics[name + '_cases_total'] = metrics[name + '_cases_found'] = 1
    score = {'metrics': metrics, 'case_contract_version': 2, 'documents': [{'document_id': 'doc', 'missing_cases': []}], 'independent_gold': True}
    return {'status': 'finished', 'purpose': 'extraction_improvement', 'candidate_revision': 'revision',
            'comparison': {'decision': 'accepted'}, 'cleanup': {'status': 'complete'},
            'sampling': {'freshness': 'history_checked'}, 'settings': {'model': 'configured-model'},
            'pipeline_tests_exit_code': 0, 'results': {'candidate': {split: deepcopy(score) for split in ('development', 'validation', 'regression')}}}


def test_quality_pass_does_not_certify_deployment():
    result = check_release_quality(completed(), 'revision')
    assert result['status'] == 'passed'
    assert result['deployment_ready'] is False
    assert 'standard_application_integration' in result['remaining_checks']


@pytest.mark.parametrize('path,value,reason', [
    (['comparison', 'decision'], 'inconclusive', 'evaluation_not_accepted'),
    (['candidate_revision'], 'old', 'processor_revision_mismatch'),
    (['cleanup', 'status'], 'pending', 'evaluation_cleanup_incomplete'),
    (['purpose'], 'grader_calibration', 'improvement_evaluation_required'),
    (['sampling', 'freshness'], 'known_fixed_sources', 'source_history_not_verified'),
    (['results', 'candidate', 'validation', 'independent_gold'], False, 'validation:human_reviewed_labels_required'),
    (['results', 'candidate', 'validation', 'metrics', 'requirement_cases_found'], 0, 'validation:requirement_cases_incomplete'),
    (['results', 'candidate', 'regression', 'metrics', 'ungrounded_attributes'], 1, 'regression:ungrounded_attributes'),
])
def test_gate_blocks_missing_evidence_and_known_errors(path, value, reason):
    cycle = completed()
    target = cycle
    for key in path[:-1]: target = target[key]
    target[path[-1]] = value
    result = check_release_quality(cycle, 'revision')
    assert result['status'] == 'blocked' and reason in result['reasons']


def test_missing_evaluation_fails_closed():
    assert check_release_quality({}, 'revision')['status'] == 'blocked'
