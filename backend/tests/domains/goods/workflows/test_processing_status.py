from copy import deepcopy
from types import SimpleNamespace

import pytest

from teoria.domains.goods.workflows.processing_status import processing_stages


def outcomes(*, documents=None, unavailable=None, dictionary=None, normalized=None, alignment=None,
             mode='standard_management'):
    return processing_stages(
        SimpleNamespace(mode=mode),
        {'documents': documents if documents is not None else [{'extraction_status': 'extracted'}],
         'unavailable_documents': unavailable or []},
        dictionary, normalized or {}, alignment,
    )


def test_expression_approval_and_rule_application_do_not_approve_unresolved_meanings():
    dictionary = {'result': {'summary': {'approved': 4}},
                  'meaning_summary': {'resolved': 1, 'unresolved': 3}}
    normalized = {'summary': {'applied': 3}}
    originals = deepcopy((dictionary, normalized))
    stages = outcomes(dictionary=dictionary, normalized=normalized)
    assert stages.extraction.status == 'completed'
    assert stages.expression_registration.status == 'completed'
    assert stages.meaning.status == 'review_required'
    assert stages.meaning.counts['unresolved_observations'] == 3
    assert stages.application.status == 'completed'
    assert stages.application.basis == 'extraction_draft'
    assert (dictionary, normalized) == originals


def test_comparison_suggestions_stay_pending_even_with_existing_resolved_links():
    stages = outcomes(dictionary={'meaning_summary': {'resolved': 1}},
                      alignment={'report': {'observations': [{'status': 'proposed'}]}})
    assert stages.meaning.status == 'review_required'
    assert stages.meaning.counts['comparison_observations'] == 1


def test_held_authoring_is_not_hidden_by_current_resolved_links():
    stages = outcomes(dictionary={'meaning_summary': {'resolved': 1},
                                 'summary': {'semantic_authoring': {'held': 1}}})
    assert stages.meaning.status == 'review_required'


def test_application_checks_entity_and_relation_deferrals_separately_from_extraction():
    stages = outcomes(normalized={'artifact_kind': 'goods_normalized_observations',
                                 'summary': {'applied': 2},
                                 'entity_summary': {'automatically_deferred': 1},
                                 'relation_summary': {'automatically_deferred': 1}})
    assert stages.extraction.status == 'completed'
    assert stages.meaning.status == 'not_requested'
    assert stages.application.status == 'partial'
    assert stages.application.counts == {'applied': 2, 'deferred': 2}
    assert stages.application.basis == 'pinned_profile'


@pytest.mark.parametrize(('documents', 'unavailable', 'expected'), [
    ([], [{'disposition': 'excluded'}], 'excluded'),
    ([], [{'disposition': 'failed'}], 'failed'),
    ([{'extraction_status': 'partial'}], [], 'partial'),
    ([{'extraction_status': 'extracted'}], [{'disposition': 'failed'}], 'partial'),
])
def test_extraction_status_uses_only_source_outcomes(documents, unavailable, expected):
    stages = outcomes(documents=documents, unavailable=unavailable)
    assert stages.extraction.status == expected
    assert stages.application.status == 'not_applicable'


def test_disabled_registration_does_not_manufacture_a_meaning_result():
    stages = outcomes(mode='document_processing', normalized={'summary': {'applied': 1}})
    assert stages.expression_registration.status == 'not_requested'
    assert stages.meaning.status == 'not_requested'
    assert stages.application.basis == 'fixed_extraction_rules'
