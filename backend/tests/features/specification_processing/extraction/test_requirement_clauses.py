"""General clauses stay source-backed without blocking product specification extraction."""
import copy
import pytest
from teoria.features.specification_processing.extraction.attribute_validation import fragment_coverage, uncovered
from teoria.features.specification_processing.extraction.requirement_clauses import other_requirements, validate_legacy_obligation


def source_case(text='법령을 준수할 것'):
    fragment = {'id':'f','node_id':'n','text':text,'start':0,'end':len(text),'expected_role':'technical_requirement'}
    document = {'nodes':[{'node_id':'n','text':text,'native_ref':'/blocks/0'}]}
    graph = {'entities':[{'id':'root','name':'차량','evidence':[{'node_id':'title'}]}]}
    return fragment,document,graph


@pytest.mark.parametrize('role',['general_requirement','delivery_requirement'])
def test_other_clause_does_not_require_attribute_or_duty_decomposition(role):
    f,_,graph=source_case();f['expected_role']=role
    assert not uncovered([[f]],[],graph=graph)
    assert fragment_coverage([[f]],[],graph=graph)[0]['coverage_status']=='other_requirement_preserved'


def test_repeated_heading_matches_only_unique_grounded_name():
    f, document, graph = source_case('3) 데이터 전송장치')
    f['expected_role'] = 'target_mention'
    graph['entities'] = [{'id': 'device', 'name': '데이터 전송장치', 'evidence': [{'node_id': 'inventory'}]}]
    result = fragment_coverage([[f]], [], graph=graph)
    assert result[0]['coverage_status'] == 'repeated_target_mention'
    assert not uncovered([[f]], [], graph=graph)
    graph['entities'].append({'id': 'another', 'name': '데이터 전송장치', 'evidence': [{'node_id': 'other'}]})
    assert uncovered([[f]], [], graph=graph)  # ambiguous ownership is not silently merged


@pytest.mark.parametrize('text', ['데이터 전송장치 2대 이상', '데이터 전송장치를 설치할 것'])
def test_real_requirements_are_not_covered_by_an_existing_item_name(text):
    f, document, graph = source_case(text)
    f['expected_role'] = 'technical_requirement'
    graph['entities'] = [{'id': 'device', 'name': '데이터 전송장치', 'evidence': [{'node_id': 'n'}]}]
    assert uncovered([[f]], [], graph=graph)


def test_misclassified_target_mention_with_obligation_still_needs_extraction():
    f, _, graph = source_case('데이터 전송장치를 설치할 것')
    f['expected_role'] = 'target_mention'
    graph['entities'] = [{'id': 'device', 'name': '데이터 전송장치', 'evidence': [{'node_id': 'n'}]}]
    assert fragment_coverage([[f]], [], graph=graph)[0]['coverage_status'] == 'missing_requirement'



def test_legacy_duties_render_as_original_clauses_and_are_still_source_validated():
    f,document,graph=source_case()
    duty={'observation_type':'obligation','subject_ids':['root'],'text':f['text'],
          'modality':'required','action_raw':f['text'],'actor_raw':None,'modality_raw':'할 것','conditions_raw':[],
          'evidence':[{'node_id':'n','quote':f['text'],'char_start':0,'char_end':len(f['text'])}]}
    validate_legacy_obligation(duty,{'root'},document)
    bad=copy.deepcopy(duty);bad['conditions_raw']=['납품 전에']
    with pytest.raises(ValueError):validate_legacy_obligation(bad,{'root'},document)
    clause={'observation_type':'source_clause','category':'other','text':f['text'],
            'evidence':[{'node_id':'n'}]}
    assert other_requirements({'requirements':[duty,clause]})==[clause]


def test_report_keeps_other_requirements_as_source_text_only():
    from teoria.features.specification_processing.reporting import render_report
    f,document,graph=source_case()
    clause={'observation_type':'source_clause','category':'other','subject_ids':[],
            'text':f['text'],'evidence':[{'node_id':'n'}]}
    row={**graph,'document_id':'vehicle','source':{'path':'vehicle.hwpx'},'attributes':[],
         'relations':[],'requirements':[clause]}
    report=render_report({'documents':[row],'unavailable_documents':[]},{'summary':{}},'fixture')
    assert '<details><summary>기타 요구사항</summary>' in report
    assert f['text'] in report and '구조화된 의무' not in report
