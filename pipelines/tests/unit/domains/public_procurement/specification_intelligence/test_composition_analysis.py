import copy
import hashlib
import json
import subprocess
import sys

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.composition_analysis import (
    CompositionProposal, comparison_name, evaluate_components, validate_composition,
)
from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import build_document_evidence


@pytest.fixture
def case():
    native = {'success': True, 'blocks': [
        {'type':'paragraph','text':'완성 특수차량'},
        {'type':'paragraph','text':'전력시스템'},
        {'type':'paragraph','text':'인버터 정격출력 3kW 이상'},
        {'type':'paragraph','text':'기관이 별도 제작하는 케이지 800mm'},
        {'type':'paragraph','text':'납품기한 60일'},
        {'type':'image','text':'unreadable'},
    ]}
    raw = json.dumps(native).encode()
    doc = build_document_evidence(native, document_id='d',parse_run_id='p',native_sha256=hashlib.sha256(raw).hexdigest())
    def t(ident, name, role, parent, relation, index):
        return {'target_id':ident,'name':name,'role':role,'nature':'system','parent_id':parent,
                'relation':relation,'relationship_basis':'explicit','reason':'원문 근거',
                'node_ids':[f'n{index:05}'],
                'evidence':[{'document_id':'d','node_id':f'n{index:05}','quote':native['blocks'][index]['text']}]}
    proposal = {
        'document_id':'d','native_sha256':doc.native_sha256,'analysis_method':'codex_interactive_reading',
        'reference_seen':True,'revision':'r1','limitations':['OCR 제외, 부분 검토'],
        'targets':[t('root','완성 특수차량','root',None,'ROOT',0),
                   t('power','전력시스템','primary','root','REVIEW_UNIT_OF',1),
                   t('inverter','인버터','detail','power','DETAIL_OF',2),
                   t('cage','케이지','external','root','REFERENCE_ONLY',3)],
        'requirement_excerpts':[{'observation_id':'o1','owner_id':'inverter','property_raw':'정격출력',
                                 'value_text':'3kW 이상','modality':'required','notes':'원문 보존',
                                 'evidence':[{'document_id':'d','node_id':'n00002','quote':'인버터 정격출력 3kW 이상'}]}],
    }
    return native, doc, proposal


def checked(case, proposal=None):
    return validate_composition(CompositionProposal.model_validate(proposal or case[2]),case[1])


def test_primary_projection_excludes_nested_and_external_and_preserves_gaps(case):
    result=checked(case)
    assert result['errors']==[]
    assert result['primary_units']==[{'target_id':'power','name':'전력시스템'}]
    assert result['unassigned_text_node_ids']==['n00004']
    assert result['unassessed_native_refs']==['/blocks/5']
    assert result['semantic_review_status']=='pending'
    assert result['automatic_compliance_ready'] is False


@pytest.mark.parametrize('mutation,error',[
    ('duplicate','duplicate_target_id'),('cycle','cycle'),('unknown_parent','invalid_parent'),
    ('promoted_detail','invalid_parent'),('reference_relation','role_relation_mismatch'),
    ('missing_quote','quote_not_in_source'),('unknown_node','unknown_node'),
    ('owner_reference','invalid_requirement_owner'),('owner_scope','requirement_outside_owner_scope'),
    ('invented_value','value_not_in_quote'),('blank_value','value_not_in_quote'),
    ('duplicate_observation','duplicate_observation_id'),
])
def test_invalid_graph_and_evidence_are_rejected(case, mutation,error):
    p=copy.deepcopy(case[2])
    if mutation=='duplicate': p['targets'].append(copy.deepcopy(p['targets'][1]))
    if mutation=='cycle': p['targets'][2]['parent_id']='inverter'
    if mutation=='unknown_parent': p['targets'][2]['parent_id']='missing'
    if mutation=='promoted_detail': p['targets'][2]['role']='primary'; p['targets'][2]['relation']='REVIEW_UNIT_OF'
    if mutation=='reference_relation': p['targets'][3]['relation']='DETAIL_OF'
    if mutation=='missing_quote': p['targets'][1]['evidence'][0]['quote']='수냉장치'
    if mutation=='unknown_node': p['targets'][1]['node_ids'].append('n99999')
    if mutation=='owner_reference': p['requirement_excerpts'][0]['owner_id']='cage'
    if mutation=='owner_scope': p['requirement_excerpts'][0]['owner_id']='power'
    if mutation=='invented_value': p['requirement_excerpts'][0]['value_text']='30kW'
    if mutation=='blank_value': p['requirement_excerpts'][0]['value_text']='  '
    if mutation=='duplicate_observation': p['requirement_excerpts'].append(copy.deepcopy(p['requirement_excerpts'][0]))
    assert any(error in e for e in checked(case,p)['errors'])


def test_changed_native_identity_is_rejected(case):
    p=copy.deepcopy(case[2]); p['native_sha256']='f'*64
    with pytest.raises(ValueError,match='identity/hash'): checked(case,p)


def test_reference_comparison_preserves_model_parentheses():
    assert comparison_name('카메라(2대)(동적주행성능시험)')==comparison_name('카메라')
    assert comparison_name('카메라(IR)')!=comparison_name('카메라(UV)')


def test_evaluation_exposes_deleted_or_duplicated_primary(case):
    p=CompositionProposal.model_validate(case[2])
    result=evaluate_components(p,['전력 시스템','바닥 레일 시스템'])
    assert (result['tp'],result['fp'],result['fn'])==(1,0,1)
    assert result['recall']==0.5
    p.targets.append(p.targets[1].model_copy(update={'target_id':'duplicate_unit'}))
    result=evaluate_components(p,['전력 시스템'])
    assert (result['tp'],result['fp'],result['fn'])==(1,1,0)
    assert result['precision']==0.5
    assert result['semantic_accuracy_measured'] is False


def test_valid_quote_does_not_prove_semantic_name_or_complete_extraction(case):
    p=copy.deepcopy(case[2]); p['targets'][1]['name']='근거 없는 이름'
    assert checked(case,p)['errors']==[]
    result=evaluate_components(CompositionProposal.model_validate(p),['전력시스템'])
    assert (result['tp'],result['fp'],result['fn'])==(0,1,1)
    # A removed component can leave a structurally valid graph. Source review and
    # independent references are necessary; do not equate structure with recall.
    p['targets']=[p['targets'][0],p['targets'][3]]; p['requirement_excerpts']=[]
    assert checked(case,p)['errors']==[]
    assert evaluate_components(CompositionProposal.model_validate(p),['전력시스템'])['fn']==1


def test_cli_prepares_without_reference_and_never_overwrites(case,tmp_path):
    native=tmp_path/'native.json'; native.write_text(json.dumps(case[0]))
    output=tmp_path/'context.json'
    command=[sys.executable,'-m','teoria_pipelines.domains.public_procurement.specification_intelligence.composition_analysis',
             'prepare','--native',str(native),'--document-id','d','--output',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    context=json.loads(output.read_text())
    assert 'output_schema' in context and len(context['source']['nodes'])==6
    assert 'expected_components' not in context
    original=output.read_bytes()
    assert subprocess.run(command,capture_output=True,text=True).returncode==2
    assert output.read_bytes()==original
