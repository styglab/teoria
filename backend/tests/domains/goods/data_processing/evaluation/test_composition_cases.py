"""Closed source lists detect extra/missing children; explicit quantities retain their owners."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from teoria.domains.goods.data_processing.evaluation.cases import EvaluationDocument
from teoria.domains.goods.data_processing.evaluation.scoring import score_extraction, compare_runs


def example():
    fixture=json.loads((Path(__file__).parent/'fixtures/lcms_composition_cases.json').read_text())
    expected=EvaluationDocument(document_id='lcms',source_uri='file:///source.pdf',filename=fixture['source_name'],
                                sha256=fixture['source_sha256'],**fixture['cases'])
    nodes=fixture['source_nodes']
    def refs(text):
        return [{'node_id':n['node_id']} for n in nodes if text in n['text']]
    root=expected.compositions[0].parent
    entities=[{'id':str(i),'name':case.name,'kind':'equipment','evidence':refs(case.name)}
              for i,case in enumerate(expected.entities)]
    ids={e['name']:e['id'] for e in entities}
    relations=[{'source_id':ids[name],'target_id':ids[root],'kind':'component_of','evidence':refs(name)}
               for name in expected.compositions[0].children]
    relations.append({'source_id':ids['PC SYSTEM'],'target_id':ids['데이터 처리 시스템'],
                      'kind':'component_of','evidence':refs('PC SYSTEM')})
    quantities=[{'entity_id':ids[q.subject],'value_raw':q.value_raw,'unit_raw':q.unit_raw,
                 'source_node_ids':[n['node_id'] for n in nodes]} for q in expected.quantities]
    actual={'document_id':'lcms','source':{'sha256':expected.sha256},'entities':entities,'relations':relations,
            'attributes':[],'declared_quantities':quantities,'parsed_document':{'nodes':nodes},'extraction_status':'partial'}
    return expected,actual


def score(expected,actual):return score_extraction({'documents':[actual]},[expected])


def test_complete_lcms_direct_list_parent_and_nine_quantities_pass():
    expected,actual=example();metrics=score(expected,actual)['metrics']
    assert metrics['composition_cases_found']==metrics['composition_cases_total']==1
    assert metrics['relation_cases_found']==1
    assert metrics['quantity_cases_found']==metrics['quantity_cases_total']==9


@pytest.mark.parametrize('mutation',['missing','extra','duplicate_target','missing_parent'])
def test_partial_or_polluted_direct_lists_fail_with_diagnostics(mutation):
    expected,actual=example()
    if mutation=='missing':actual['relations'].pop(0)
    elif mutation=='extra':actual['relations'][-1]['target_id']='0'  # PC promoted to root.
    elif mutation=='duplicate_target':
        duplicate=deepcopy(actual['entities'][1]);duplicate['id']='duplicate';actual['entities'].append(duplicate)
        actual['relations'].append({**actual['relations'][0],'source_id':'duplicate'})
    else:actual['entities'].pop(0)
    result=score(expected,actual)
    assert result['metrics']['composition_cases_found']==0
    assert result['documents'][0]['composition_differences']
    if mutation=='extra':assert result['metrics']['relation_cases_found']==0


def test_multiple_relation_kinds_to_the_same_child_do_not_double_count_a_component():
    expected,actual=example()
    actual['relations'].append({**actual['relations'][0],'kind':'in_procurement_scope'})
    actual['relations'].reverse()
    assert score(expected,actual)['metrics']['composition_cases_found']==1


@pytest.mark.parametrize('mutation',['value','unit','owner','evidence','duplicate'])
def test_wrong_quantity_or_missing_owner_evidence_fails(mutation):
    expected,actual=example();quantity=actual['declared_quantities'][0]
    if mutation=='value':quantity['value_raw']='2'
    elif mutation=='unit':quantity['unit_raw']='set'
    elif mutation=='owner':quantity['entity_id']='unknown'
    elif mutation=='evidence':quantity['source_node_ids']=[]
    else:actual['declared_quantities'].append(deepcopy(quantity))
    assert score(expected,actual)['metrics']['quantity_cases_found']==8


def test_failed_documents_keep_composition_and_quantity_denominators():
    expected,_=example();result=score_extraction({'documents':[]},[expected])
    assert result['metrics']['composition_cases_total']==1
    assert result['metrics']['quantity_cases_total']==9
    assert 'composition:0' in result['documents'][0]['missing_cases']
    assert 'quantity:8' in result['documents'][0]['missing_cases']


def test_new_case_regressions_reject_the_comparison():
    expected,actual=example();before=score(expected,actual)
    actual['relations'][-1]['target_id']='0';after=score(expected,actual)
    result=compare_runs({'development':before},{'development':after},True)
    assert result['decision']=='rejected'
    assert 'development:composition_regression' in result['reasons']
