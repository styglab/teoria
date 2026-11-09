"""Explicit source-name calibration preserves value, unit and subject checks."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from teoria.domains.goods.data_processing.evaluation.cases import EvaluationDocument
from teoria.domains.goods.data_processing.evaluation.scoring import score_extraction


def example():
    fixture=json.loads((Path(__file__).parent/'fixtures/vacuum_power_cases.json').read_text())
    expected=EvaluationDocument(document_id='pump',source_uri='file:///source.pdf',
        filename=fixture['source_name'],sha256=fixture['source_sha256'],**fixture['cases'])
    actual={'document_id':'pump','source':{'sha256':expected.sha256},
        'entities':[{'id':'root','name':'고효율 진공펌프','kind':'equipment','evidence':[{'node_id':'n00109'}]}],
        'relations':[],'attributes':[], 'parsed_document':{'nodes':fixture['source_nodes']}}
    for index,(value,node_id) in enumerate([('600','n00125'),('425','n00131')]):
        actual['attributes'].append({'id':str(index),'subject_ids':['root'],'property_key':'power',
            'value_raw':value,'unit_raw':'kW','operator':'eq','qualifiers_raw':[],
            'evidence':{'node_id':node_id}})
    return expected,actual


def metrics(expected,actual):
    return score_extraction({'documents':[actual]},[expected])['metrics']


def test_explicit_names_fix_false_missing_cases_without_changing_extraction():
    expected,actual=example();before=deepcopy(actual)
    narrow=expected.model_copy(update={'entity_aliases':{}})
    assert metrics(narrow,actual)['requirement_cases_found']==0
    result=metrics(expected,actual)
    assert result['entity_cases_found']==1 and result['requirement_cases_found']==2
    assert actual==before


@pytest.mark.parametrize('mutation',['value','unit','operator','wrong_subject','duplicate_subject','unknown_name'])
def test_name_calibration_does_not_admit_wrong_facts_or_ambiguous_targets(mutation):
    expected,actual=example()
    if mutation=='value':actual['attributes'][0]['value_raw']='60'
    elif mutation=='unit':actual['attributes'][0]['unit_raw']='W'
    elif mutation=='operator':actual['attributes'][0]['operator']='lte'
    elif mutation=='wrong_subject':actual['attributes'][0]['subject_ids']=[]
    elif mutation=='duplicate_subject':
        actual['entities'].append({**actual['entities'][0],'id':'duplicate'})
    else:actual['entities'][0]['name']='초고효율 진공펌프'
    assert metrics(expected,actual)['requirement_cases_found']<2
