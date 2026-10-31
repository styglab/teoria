"""Source-backed role contracts; mocked decisions do not measure model accuracy."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from teoria.features.specification_processing.parsing.document_assessment import assess_document,extraction_node_ids
from teoria.features.specification_processing.extraction.attribute_chunking import make_chunks


def form():
    data=json.loads((Path(__file__).parent/'fixtures/comparison_form_source.json').read_text())
    return {'document_id':'form','nodes':data['nodes']}

async def test_source_comparison_form_is_excluded_only_with_complete_explicit_assessment(tmp_path):
    document=form()
    model=AsyncMock();model.generate.return_value={'document_kind':'template','groups':[
        {'role':'template','node_ids':[n['node_id'] for n in document['nodes']]}],'rationale':'Unfilled bidder comparison form.'}
    result=await assess_document(document,model,tmp_path)
    assert result['excluded'] and result['document_kind']=='template'
    model.generate.return_value['groups'][0]['node_ids'].pop()
    result=await assess_document(document,model,tmp_path)
    assert not result['excluded'] and result['status']=='needs_review'

@pytest.mark.parametrize('bad',[TimeoutError(),{'document_kind':'template','groups':[{'role':'template','node_ids':['invented']}],'rationale':'invalid'}])
async def test_assessment_failure_or_invalid_source_ids_never_excludes_input(tmp_path,bad):
    model=AsyncMock()
    if isinstance(bad,Exception):model.generate.side_effect=bad
    else:model.generate.return_value=bad
    result=await assess_document(form(),model,tmp_path)
    assert result['document_kind']=='unknown' and not result['excluded']
    document=form();document['document_assessment']=result
    assert extraction_node_ids(document)=={n['node_id'] for n in document['nodes']}


def test_mixed_passages_preserve_requirements_unknowns_offsets_and_source_context():
    texts=['4. 기술 지원 사항','CPU 16 Core 이상','- HW/SW 설치 및 사용 매뉴얼','입찰 참가 신청','불명확한 조건']
    document={'nodes':[{'node_id':str(i),'text':t,'kind':'paragraph','parent_id':None,'page':1} for i,t in enumerate(texts)],
        'document_assessment':{'node_roles':dict(zip(map(str,range(5)),['heading','technical_requirement','delivery_requirement','procedure','unknown']))}}
    chunks=make_chunks({'entities':[]},document)
    fragments=[f for chunk in chunks for f in chunk]
    assert {f['node_id'] for f in fragments}=={'1','4'}
    assert all(document['nodes'][int(f['node_id'])]['text'][f['start']:f['end']]==f['text'] for f in fragments)
    assert document['nodes'][0]['text']=='4. 기술 지원 사항'


def test_entity_mention_and_other_delivery_clauses_do_not_require_properties():
    from teoria.features.specification_processing.extraction.attribute_validation import uncovered
    node={'id':'f','node_id':'n','text':'HW/SW 설치 및 사용 매뉴얼','expected_role':'target_mention'}
    graph={'entities':[{'id':'manual','evidence':[{'node_id':'n'}]}]}
    assert uncovered([[node]],[],graph=graph)==[]
    obligation={**node,'expected_role':'delivery_requirement'}
    assert uncovered([[obligation]],[],graph=graph)==[]


def test_clause_context_preserves_split_source_sentence_without_joining_or_changing_values():
    from teoria.features.specification_processing.extraction.attribute_validation import fragment_context
    document={'nodes':[{'node_id':str(i),'text':t,'kind':'paragraph','parent_id':None,'page':1} for i,t in enumerate([
        '장애 접수 시 3시간 이내에 현장을 방문하여 장애 해결','작업을 시작하여야 한다.','2 / 3','작업을 시작하여야 한다.'])],
        'document_assessment':{'clause_groups':[['0','1','3']]}}
    context=fragment_context(document,{'node_id':'3'})
    assert {'0','1'}<={row[0] for row in context}
    assert document['nodes'][0]['text']=='장애 접수 시 3시간 이내에 현장을 방문하여 장애 해결'


async def test_non_specification_disposition_prevents_following_extraction(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from teoria.features.specification_processing import tasks
    from teoria.features.specification_processing.parsing import document_parser
    document=form()
    model=AsyncMock();model.generate.return_value={'document_kind':'template','groups':[
        {'role':'template','node_ids':[n['node_id'] for n in document['nodes']]}],'rationale':'Blank comparison form.'}
    monkeypatch.setattr(tasks,'runner',lambda _:model)
    monkeypatch.setattr(document_parser,'parse_document',AsyncMock(return_value=document))
    work=tmp_path/'work.json';work.write_text(json.dumps([{'document_id':'form','source_path':'unused.hwp'}]))
    request=SimpleNamespace(concurrency=1,parser_python=None)
    await tasks.parse_documents.fn(request,str(tmp_path))
    assert json.loads(work.read_text())[0]['failure']['disposition']=='excluded'
    followup=AsyncMock()
    await tasks.each_document(str(tmp_path),request,followup)
    followup.assert_not_awaited()


def test_report_distinguishes_excluded_form_from_parser_failure():
    from teoria.features.specification_processing.reporting import render_report
    corpus={'documents':[],'unavailable_documents':[
        {'document_id':'form','reason':'not_specification','disposition':'excluded'},
        {'document_id':'scan','reason':'SpecificationProcessingError','code':'needs_ocr'}]}
    result=render_report(corpus,{'summary':{},'documents':[]},'fixture')
    assert '1개 실패, 1개 대상 제외' in result
    assert 'form: 대상 아님' in result and 'scan: 처리 실패' in result and 'needs_ocr' in result


def test_numbered_inventory_name_is_entity_coverage_even_if_role_judgment_is_too_broad():
    from teoria.features.specification_processing.extraction.attribute_validation import uncovered
    # LCMS original inventory node n00021 and adjacent technical labels.
    mention={'id':'name','node_id':'n','text':'1. 질량분석기','expected_role':'technical_requirement'}
    graph={'entities':[{'name':'질량분석기','evidence':[{'node_id':'n'}]}]}
    assert uncovered([[mention]],[],graph=graph)==[]
    constraint={**mention,'text':'1. 질량분석기 2대 이상'}
    assert uncovered([[constraint]],[],graph=graph)==[constraint]


async def test_notice_deadline_does_not_create_a_specification_but_technical_conditions_prevent_exclusion(tmp_path):
    document={'document_id':'notice','nodes':[{'node_id':'n','kind':'paragraph','text':'납품 기한: 계약 후 30일'}]}
    model=AsyncMock();model.generate.return_value={'document_kind':'procurement_notice','groups':[
        {'role':'delivery_requirement','node_ids':['n']}],'rationale':'Tender administration deadline only.'}
    assert (await assess_document(document,model,tmp_path))['excluded']
    model.generate.return_value['groups'][0]['role']='technical_requirement'
    assert not (await assess_document(document,model,tmp_path))['excluded']
    model.generate.return_value['groups'][0]['role']='unknown'
    assert not (await assess_document(document,model,tmp_path))['excluded']


async def test_notice_inventory_metadata_is_not_technical_but_performance_values_are_retained(tmp_path):
    document={'document_id':'notice','nodes':[{'node_id':str(i),'kind':'paragraph','text':t} for i,t in enumerate(['수량:','1','단위:','식'])]}
    model=AsyncMock();model.generate.return_value={'document_kind':'procurement_notice','groups':[
        {'role':'heading','node_ids':['0','2']},{'role':'technical_requirement','node_ids':['1','3']}],
        'rationale':'Purchase quantity metadata only.'}
    assert (await assess_document(document,model,tmp_path))['excluded']
    document['nodes'][0]['text']='CPU 코어 수:';document['nodes'][1]['text']='16';document['nodes'][3]['text']='Core'
    assert not (await assess_document(document,model,tmp_path))['excluded']


async def test_general_law_clauses_stay_available_but_do_not_replace_concrete_product_specs(tmp_path):
    texts=['제작사는 관련 법령을 준수할 것','허용하중: 200kg 이상\n세척·소독이 용이한 재질로 마감','납품 시 매뉴얼 제출']
    document={'document_id':'vehicle','nodes':[{'node_id':str(i),'kind':'paragraph','text':t} for i,t in enumerate(texts)]}
    model=AsyncMock();model.generate.return_value={'document_kind':'specification','groups':[
        {'role':'general_requirement','node_ids':['0']},{'role':'technical_requirement','node_ids':['1']},
        {'role':'delivery_requirement','node_ids':['2']}],'rationale':'Product constraints with other terms.'}
    document['document_assessment']=await assess_document(document,model,tmp_path)
    assert document['document_assessment']['status']=='classified'
    assert extraction_node_ids(document)=={'0','1','2'}
    fragments=[f for c in make_chunks({'entities':[]},document) for f in c]
    assert [f['node_id'] for f in fragments]==['1']
    assert '세척·소독이 용이한 재질' in fragments[0]['text']
