"""Source-backed examples and controlled counterexamples for the grading contract."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from teoria.features.specification_processing.evaluation_cases import EvaluationDocument,EntityCase,RequirementCase
from teoria.features.specification_processing.evaluation_scoring import score_extraction,qualifier_key


def example(text='GPU는 최소 24GB 이상의 VRAM을 가진 제품 1개 이상을 포함',name='GPU',value='24',unit='GB',operator='gte',qualifiers=None):
    expected=EvaluationDocument(document_id='doc',notice_number='notice',filename='source.hwp',source_uri='file:///source.hwp',sha256='a'*64,
        classification_code='4321150102',classification_evidence={'path':'/metadata.json','sha256':'b'*64,'code_pointer':'/code','notice_pointer':'/notice'},
        requirements=[RequirementCase(subjects=[name],value_raw=value,unit_raw=unit,operator=operator,source_text=text)])
    attribute={'id':'a','subject_ids':['e'],'property_key':'capacity','value_raw':value,'unit_raw':unit,'operator':operator,
        'operator_raw':None,'qualifiers_raw':qualifiers or [],'semantic_role':'requirement_candidate','semantic_scope':'per_component','evidence':{'node_id':'n'}}
    actual={'document_id':'doc','source':{'sha256':'a'*64},'entities':[{'id':'e','name':name,'kind':'equipment','evidence':[{'node_id':'n'}]}],
        'relations':[],'attributes':[attribute],'parsed_document':{'nodes':[{'node_id':'n','text':text}]},'extraction_status':'extracted'}
    return expected,actual


def found(expected,actual):return score_extraction({'documents':[actual]},[expected])['metrics']['requirement_cases_found']


def test_additional_source_conditions_do_not_erase_a_correct_capacity():
    expected,actual=example(qualifiers=['최소','가진 제품 1개 이상을 포함'])
    assert expected.requirements[0].qualifiers_raw is None and found(expected,actual)==1
    expected.requirements[0].qualifiers_raw=[]
    assert found(expected,actual)==1


def test_explicit_absence_of_conditions_is_still_checked():
    expected,actual=example(qualifiers=['최소'])
    expected.requirements[0].qualifier_mode='exact';expected.requirements[0].qualifiers_raw=[]
    assert found(expected,actual)==0
    actual['attributes'][0]['qualifiers_raw']=[]
    assert found(expected,actual)==1


def test_exact_without_an_explicit_list_is_not_a_valid_oracle():
    with pytest.raises(ValidationError,match='explicit list'):
        RequirementCase(subjects=['GPU'],value_raw='24',unit_raw='GB',operator='gte',source_text='24GB',qualifier_mode='exact')


def test_only_balanced_outer_presentation_brackets_are_ignored():
    expected,actual=example('메모리 용량: 256GB (32GB * 8EA) 이상','메모리','256','GB',qualifiers=['32GB * 8EA'])
    expected.requirements[0].qualifiers_raw=['(32GB * 8EA)']
    assert found(expected,actual)==1
    assert qualifier_key('(32GB)*(8EA)')!='32GB*8EA'
    assert qualifier_key('32GB OR 8EA')!=qualifier_key('32GB AND 8EA')
    assert qualifier_key('미장착')!=qualifier_key('장착')


def test_installed_count_can_keep_the_original_installation_condition():
    expected,actual=example('CPU 2개 장착','CPU','2','개','eq',['장착'])
    assert found(expected,actual)==1


@pytest.mark.parametrize('field,value',[('value_raw','23'),('unit_raw','TB'),('operator','lte'),
    ('qualifiers_raw',['지원되지 않는 조건']),('subject_ids',['other'])])
def test_wrong_values_units_operators_subjects_and_ungrounded_conditions_fail(field,value):
    expected,actual=example();actual['attributes'][0][field]=value
    actual['entities'].append({'id':'other','name':'RAM','kind':'equipment','evidence':[{'node_id':'n'}]})
    assert found(expected,actual)==0


def test_missing_required_and_explicitly_forbidden_conditions_fail():
    expected,actual=example('GPU 24GB 이상, 필수 장착; 옵션 선택 불가',qualifiers=['필수 장착'])
    expected.requirements[0].qualifiers_raw=['필수 장착']
    expected.requirements[0].forbidden_qualifiers=['옵션']
    assert found(expected,actual)==1
    actual['attributes'][0]['qualifiers_raw']=[]
    assert found(expected,actual)==0
    actual['attributes'][0]['qualifiers_raw']=['필수 장착','옵션']
    assert found(expected,actual)==0


@pytest.mark.parametrize('field,correct,wrong',[('role','requirement_candidate','supported_capability'),('scope','per_component','system_total')])
def test_source_backed_conditions_cannot_override_labelled_role_or_scope(field,correct,wrong):
    expected,actual=example();setattr(expected.requirements[0],field,correct)
    actual['attributes'][0]['semantic_'+field]=wrong
    assert found(expected,actual)==0


def test_entity_existence_is_distinct_from_a_particular_mention():
    expected,actual=example()
    expected.entities=[EntityCase(name='GPU',source_text=actual['parsed_document']['nodes'][0]['text'])]
    actual['parsed_document']['nodes'].append({'node_id':'label','text':'GPU'})
    actual['entities'][0]['evidence']=[{'node_id':'label'}]
    result=score_extraction({'documents':[actual]},[expected])
    assert result['metrics']['entity_cases_found']==1
    expected.entities[0].evidence_mode='mention'
    assert score_extraction({'documents':[actual]},[expected])['metrics']['entity_cases_found']==0
    actual['entities'][0]['evidence']=[{'node_id':'unknown'}]
    expected.entities[0].evidence_mode='existence'
    assert score_extraction({'documents':[actual]},[expected])['metrics']['entity_cases_found']==0


def test_frozen_source_aliases_work_without_fuzzy_name_matching():
    expected,actual=example('그래픽 처리장치(GPU) GPU 24GB 이상')
    expected.requirements[0].subjects=['그래픽 처리장치(GPU)']
    assert found(expected,actual)==0
    expected.entity_aliases={'그래픽 처리장치(GPU)':['GPU']}
    assert found(expected,actual)==1
    actual['entities'][0]['name']='GPU2'
    assert found(expected,actual)==0


def test_duplicate_component_names_require_an_owner_for_attribute_identity():
    expected,actual=example('GPU 24GB 이상 서버 A 서버 B')
    actual['entities'] += [{'id':'other_gpu','name':'GPU','kind':'equipment','evidence':[{'node_id':'n'}]},
                          {'id':'server_a','name':'서버 A','kind':'equipment','evidence':[{'node_id':'n'}]},
                          {'id':'server_b','name':'서버 B','kind':'equipment','evidence':[{'node_id':'n'}]}]
    actual['relations']=[{'source_id':'e','target_id':'server_b','kind':'component_of','evidence':[{'node_id':'n'}]}]
    assert found(expected,actual)==0
    expected.requirements[0].owner='서버 A'
    assert found(expected,actual)==0
    expected.requirements[0].owner='서버 B'
    assert found(expected,actual)==1
    expected.entities=[EntityCase(name='GPU',source_text='GPU',owner='서버 A')]
    assert score_extraction({'documents':[actual]},[expected])['metrics']['entity_cases_found']==0


def test_ambiguous_alias_groups_cannot_merge_cpu_and_gpu():
    expected,_=example();data=expected.model_dump()
    data['entity_aliases']={'CPU':['장치'],'GPU':['장치']}
    with pytest.raises(ValidationError,match='ambiguous entity alias'):EvaluationDocument.model_validate(data)


def test_different_grading_contracts_cannot_establish_an_extraction_improvement():
    from teoria.features.specification_processing.evaluation_scoring import compare_runs
    expected,actual=example()
    summary=score_extraction({'documents':[actual]},[expected])
    old=deepcopy(summary);old['case_contract_version']=1
    old['metrics']['requirement_cases_found']=0
    verdict=compare_runs({s:old for s in ('development','validation','regression')},
        {s:summary for s in ('development','validation','regression')},True)
    assert verdict['decision']=='inconclusive'
    assert any(reason.endswith(':changed_case_contract') for reason in verdict['reasons'])


def test_repeated_source_requirements_at_different_locations_are_not_extraction_duplicates():
    # R26BK01779325 repeats CPU core/thread requirements in its overview and specification table.
    expected,actual=example('CPU 16코어/32스레드','CPU','16','코어','eq')
    actual['attributes'][0]['property_key']='core_count'
    second=deepcopy(actual['attributes'][0]);second['id']='a2';second['evidence']={'node_id':'detail'}
    actual['attributes'].append(second)
    actual['parsed_document']['nodes'].append({'node_id':'detail','text':'CPU 16코어/32스레드'})
    metrics=score_extraction({'documents':[actual]},[expected])['metrics']
    assert metrics['duplicate_attributes']==0
    assert metrics['requirement_cases_found']==1


def test_same_source_observation_extracted_twice_is_still_a_duplicate():
    expected,actual=example()
    second=deepcopy(actual['attributes'][0]);second['id']='a2'
    second['evidence']['fragment_id']='retry_fragment'
    actual['attributes'].append(second)
    assert score_extraction({'documents':[actual]},[expected])['metrics']['duplicate_attributes']==1


def test_distinct_source_spans_within_the_same_node_are_preserved():
    expected,actual=example('GPU 24GB, GPU 24GB')
    first=actual['attributes'][0];first['evidence'].update(char_start=0,char_end=8)
    second=deepcopy(first);second['id']='a2';second['evidence'].update(char_start=10,char_end=18)
    actual['attributes'].append(second)
    assert score_extraction({'documents':[actual]},[expected])['metrics']['duplicate_attributes']==0
