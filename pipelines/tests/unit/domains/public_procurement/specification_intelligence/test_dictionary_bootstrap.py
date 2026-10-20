"""Synthetic contracts, including the complete fix/recheck/approve cycle."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.composition_analysis import CompositionProposal, write_json
from teoria_pipelines.domains.public_procurement.specification_intelligence.dictionary_bootstrap import (
    AnalysisBatchRequest, BatchRequest, build_draft_bundle, check_draft_bundle,
    collect_observations, load_batch, prepare_batch, sha,
)
from teoria_pipelines.domains.public_procurement.specification_intelligence.dictionary_draft import ConsolidationProposal
from teoria_pipelines.domains.public_procurement.specification_intelligence.dictionary_review import FinalReview, approve_offline_dictionary
from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import build_document_evidence
from teoria_pipelines.domains.public_procurement.specification_intelligence.document_qualification import QualificationSubmission, validate_qualification_submission
from teoria_pipelines.domains.public_procurement.specification_intelligence.requirement_discovery import DiscoveryProposal, validate_discovery

MODULE = 'teoria_pipelines.domains.public_procurement.specification_intelligence.dictionary_bootstrap'


def make_case(root: Path, start=0):
    """Ten explicitly synthetic notices; not real procurement or model extraction."""
    root.mkdir(parents=True)
    entries, rows, compositions, discoveries = [], [], {}, {}
    meanings = [
        dict(definition='실제 장착 메모리 합계',property_kind='memory_capacity',data_type='number',dimension='data_size',aggregation='total',configuration='installed',measurement_basis='system_memory'),
        dict(definition='최대 지원 메모리 합계',property_kind='memory_capacity',data_type='number',dimension='data_size',aggregation='total',configuration='supported',measurement_basis='system_memory'),
        dict(definition='CPU 기본 클럭',property_kind='clock_frequency',data_type='number',dimension='frequency',aggregation='per_instance',configuration='installed',measurement_basis='base_clock'),
        dict(definition='CPU 최대 부스트 클럭',property_kind='clock_frequency',data_type='number',dimension='frequency',aggregation='per_instance',configuration='installed',measurement_basis='boost_clock'),
    ]
    attr_ids=['installed_memory_capacity','maximum_supported_memory_capacity','cpu_base_clock','cpu_boost_clock']
    for i in range(start,start+10):
        doc=f'd{i:02}'; directory=root/doc; directory.mkdir()
        label=['RAM','Memory','메모리'][i%3]
        texts=[f'합성 테스트 공고 {i} PC 구매','시스템 메모리',f'{label} 16GB 이상 장착',
               'Memory 최대 128GB 지원','CPU 기본 2.9GHz 이상','CPU 부스트 4.1GHz 이상','교육 1회']
        native={'success':True,'blocks':[{'type':'paragraph','text':t} for t in texts]}
        raw=json.dumps(native,ensure_ascii=False).encode(); (directory/'native.json').write_bytes(raw)
        source=f'SYNTHETIC_FIXTURE_ONLY_{i}'.encode(); (directory/'source.txt').write_bytes(source)
        document=build_document_evidence(native,document_id=doc,parse_run_id='fixture',native_sha256=sha(raw))
        def ev(n):return {'document_id':doc,'node_id':f'n{n:05}','quote':texts[n]}
        q=validate_qualification_submission(QualificationSubmission(
            run_id='fixture_qualification',analysis_method='codex_interactive_reading',document_id=doc,parse_run_id='fixture',
            source_sha256=sha(source),native_sha256=sha(raw),proposal={'document_role':'procurement_specification',
            'summary':'합성 계약 시험','regions':[{'region_id':'r','decision':'REQUIREMENTS_FOUND','reason':'합성 규격','evidence':[ev(2)]}]}),document)
        write_json(directory/'qualification.json',q.model_dump())
        write_json(directory/'parse_record.json',{'document_id':doc,'parser':'kordoc','version':'synthetic_fixture',
            'status':'success','options':{'ocr':False,'formulaOcr':False}})
        entry={'document_id':doc,'notice_number':f'FIXTURE_{i}'}
        for kind,file in [('source','source.txt'),('native','native.json'),('qualification','qualification.json'),('parse_record','parse_record.json')]:
            entry[kind+'_path']=str(directory/file); entry[kind+'_sha256']=sha((directory/file).read_bytes())
        entries.append(entry)
        targets=[]
        for ident,name,role,parent,ids in [('root','PC','root',None,[0]),('memory','시스템 메모리','primary','root',[1,2,3]),('cpu','CPU','primary','root',[4,5])]:
            targets.append({'target_id':ident,'name':name,'role':role,'nature':'equipment','parent_id':parent,
                'relation':'ROOT' if role=='root' else 'REVIEW_UNIT_OF','relationship_basis':'explicit','reason':'합성 규격',
                'node_ids':[f'n{n:05}' for n in ids],'evidence':[ev(ids[0])]})
        composition={'document_id':doc,'native_sha256':sha(raw),'analysis_method':'codex_interactive_reading',
                     'reference_seen':False,'revision':'fixture_composition','targets':targets,'limitations':['합성 테스트 자료']}
        write_json(directory/'composition.json',CompositionProposal.model_validate(composition).model_dump())
        observations=[]
        for n,meaning in enumerate(meanings,start=2):
            observations.append({'observation_id':f'o{n}','owner_id':'memory' if n<4 else 'cpu',
                'raw_attribute':label if n==2 else 'Memory' if n==3 else 'CPU','raw_text':texts[n],
                'meaning':meaning,'operator':'GE','value_text':['16','128','2.9','4.1'][n-2],
                'unit_raw':'GB' if n<4 else 'GHz','modality':'required','qualifiers':[], 'evidence':[ev(n)]})
        discovery={'document_id':doc,'native_sha256':sha(raw),'composition_sha256':sha((directory/'composition.json').read_bytes()),
            'analysis_method':'codex_interactive_reading','revision':'fixture_discovery','observations':observations,
            'groups':[{'group_id':'memory_both','logic':'AND','members':['o2','o3'],'explanation':'합성 AND 조건','evidence':[ev(2),ev(3)]}],
            'coverage':[{'node_id':f'n{n:05}','decision':'observed' if 2<=n<=5 else 'non_property',
                         'observation_ids':[f'o{n}'] if 2<=n<=5 else [],'reason':'합성 검토'} for n in range(len(texts))],
            'limitations':['합성 fixture이며 실제 모델 추출 결과가 아님.']}
        write_json(directory/'discovery.json',DiscoveryProposal.model_validate(discovery).model_dump())
        compositions[doc]=composition; discoveries[doc]=discovery
        rows.append({'document_id':doc,'composition_path':str(directory/'composition.json'),'discovery_path':str(directory/'discovery.json')})
    request=BatchRequest(batch_id=f'fixture_batch_{start}',documents=entries)
    prepared=root/'prepared'; prepare_batch(request,prepared)
    analyses=AnalysisBatchRequest(prepared_batch=str(prepared),documents=rows)
    definitions=[{'attribute_id':ident,'name':meaning['definition'],'meaning':meaning,
                  'component_type_ids':['memory' if index<2 else 'cpu'],'canonical_unit':'GB' if index<2 else 'GHz',
                  'accepted_raw_units':['GB'] if index<2 else ['GHz'],'aliases':[]} for index,(ident,meaning) in enumerate(zip(attr_ids,meanings))]
    proposal={'revision':'fixture_r1','change_notes':'합성 초기 사전',
        'component_types':[{'type_id':'memory','name':'시스템 메모리','definition':'시스템의 주기억장치'},
                           {'type_id':'cpu','name':'CPU','definition':'중앙처리장치'}],
        'attributes':definitions,
        'type_bindings':[{'document_id':r['document_id'],'target_id':owner,'type_id':owner,'reason':'합성 유형'} for r in rows for owner in ['memory','cpu']],
        'decisions':[{'observation_ref':f"{r['document_id']}/o{n}",'decision':'MAP','attribute_id':attr_ids[n-2],'reason':'합성 의미 일치'} for r in rows for n in range(2,6)]}
    proposal_path=root/'consolidation.json';write_json(proposal_path,ConsolidationProposal.model_validate(proposal).model_dump())
    return dict(root=root,request=request,analyses=analyses,proposal=proposal,proposal_path=proposal_path,
                compositions=compositions,discoveries=discoveries)


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path/'fixture')


def make_review(bundle: Path, *, findings=None, fail_ids=(), previous_hash=None):
    draft=json.loads((bundle/'draft.json').read_text())
    return FinalReview(draft_sha256=sha((bundle/'draft.json').read_bytes()),source_bundle_sha256=draft['source_bundle_sha256'],
        previous_review_sha256=previous_hash,analysis_method='codex_self_review',reviewer_label='synthetic_fixture_only',
        checks=[{'review_id':key,'verdict':'FAIL' if key in fail_ids else 'PASS','notes':'합성 fixture 확인'} for key in draft['required_review_ids']],
        findings=findings or [],summary='합성 계약 시험. 실제 사전 승인 아님.')


def test_complete_pipeline_and_local_approval(case):
    assert collect_observations(case['analyses'],case['root']/'collected')==[]
    draft=build_draft_bundle(case['analyses'],case['proposal_path'],case['root']/'draft')
    assert draft['blocking_issues']==[]
    assert len(draft['catalogue']['attributes'])==4 and len(draft['requirements'])==40
    review=make_review(case['root']/'draft'); path=case['root']/'review.json';write_json(path,review.model_dump())
    rebuilt,check,*_=check_draft_bundle(case['root']/'draft',path)
    approved=approve_offline_dictionary(rebuilt,review,draft_sha256=check['draft_sha256'],review_sha256=sha(path.read_bytes()),
        reviewer_label='fixture',authorization_note='SYNTHETIC_TEST_ONLY')
    assert approved['status']=='offline_approved' and approved['published'] is False


@pytest.mark.parametrize('mutation,expected',[
    ('five','at least 10'),('same_notice','notice_number'),('same_source','source_sha256'),
    ('ocr','OCR'),('stale_qualification','hash mismatch'),('bad_native','hash mismatch'),
])
def test_batch_requires_ten_distinct_qualified_parses(case,mutation,expected):
    request=case['request'].model_dump()
    if mutation=='five':request['documents']=request['documents'][:5]
    if mutation=='same_notice':request['documents'][1]['notice_number']=request['documents'][0]['notice_number']
    if mutation=='same_source':request['documents'][1]['source_sha256']=request['documents'][0]['source_sha256']
    if mutation=='ocr':
        p=Path(request['documents'][0]['parse_record_path']);raw=json.loads(p.read_text());raw['options']['ocr']=True
        p.write_text(json.dumps(raw));request['documents'][0]['parse_record_sha256']=sha(p.read_bytes())
    if mutation=='stale_qualification':Path(request['documents'][0]['qualification_path']).write_text('{}')
    if mutation=='bad_native':Path(request['documents'][0]['native_path']).write_text('{}')
    with pytest.raises(ValueError,match=expected):prepare_batch(BatchRequest.model_validate(request),case['root']/'invalid')
    assert not (case['root']/'invalid').exists()


@pytest.mark.parametrize('mutation,error',[
    ('value','value_not_in_evidence'),('owner','evidence_outside_owner'),('coverage','incomplete_or_duplicate_node_coverage'),
    ('operator','unresolved_interpretation'),('modality','unresolved_interpretation'),('cycle','condition_cycle'),
    ('if','invalid_logic'),('unknown_member','invalid_group_reference'),
    ('numeric_substring','numeric_value_not_exact'),('operator_evidence','operator_evidence_mismatch'),
    ('qualifier','qualifier_not_in_evidence'),
])
def test_observation_and_logic_guards(case,mutation,error):
    _,documents,_=load_batch(Path(case['analyses'].prepared_batch));doc=documents[0]
    composition=CompositionProposal.model_validate(case['compositions'][doc.document_id])
    d=copy.deepcopy(case['discoveries'][doc.document_id])
    if mutation=='value':d['observations'][0]['value_text']='16000'
    if mutation=='owner':d['observations'][0]['owner_id']='cpu'
    if mutation=='coverage':d['coverage'].pop()
    if mutation=='operator':d['observations'][0]['operator']='UNKNOWN'
    if mutation=='modality':d['observations'][0]['modality']='uncertain'
    if mutation=='cycle':d['groups'][0]['members']=['o2','memory_both']
    if mutation=='if':d['groups'][0]['logic']='IF'
    if mutation=='unknown_member':d['groups'][0]['members']=['o2','absent']
    if mutation=='numeric_substring':d['observations'][0]['value_text']='1'
    if mutation=='operator_evidence':d['observations'][0].update(operator='LE',operator_text='이상')
    if mutation=='qualifier':d['observations'][0]['qualifiers']=['CPU당 기준']
    errors=validate_discovery(DiscoveryProposal.model_validate(d),composition,doc,
        composition_sha256=sha(Path(case['analyses'].documents[0].composition_path).read_bytes()))
    assert any(error in e for e in errors)


@pytest.mark.parametrize('mutation,error',[
    ('merge_scopes','meaning_scope_mismatch'),('wrong_type','component_type_mismatch'),
    ('wrong_units','unit_dimension_unverified'),('unresolved','unresolved_mapping'),
    ('drop','decisions_do_not_cover'),('alias','alias_not_in_evidence'),('unused','new_attribute_without_mapped_evidence'),
])
def test_dictionary_definition_and_mapping_guards(case,mutation,error):
    p=copy.deepcopy(case['proposal'])
    if mutation=='merge_scopes':p['decisions'][1]['attribute_id']='installed_memory_capacity'
    if mutation=='wrong_type':p['type_bindings'][0]['type_id']='cpu'
    if mutation=='wrong_units':p['attributes'][0]['canonical_unit']='GHz'
    if mutation=='unresolved':p['decisions'][0].update(decision='HOLD',attribute_id=None)
    if mutation=='drop':p['decisions'].pop()
    if mutation=='alias':
        p['attributes'][0]['aliases']=[{'expression':'존재하지않음','context':'합성 문맥','evidence':case['discoveries']['d00']['observations'][0]['evidence']}]
    if mutation=='unused':
        a=copy.deepcopy(p['attributes'][0]);a.update(attribute_id='unused',name='사용하지 않은 정의');p['attributes'].append(a)
    path=case['root']/'changed.json';write_json(path,p)
    draft=build_draft_bundle(case['analyses'],path,case['root']/'changed')
    assert any(error in e for e in draft['blocking_issues'])


def test_repair_requires_new_review_and_keeps_previous_findings(case):
    broken=copy.deepcopy(case['proposal']);broken['decisions'][1]['attribute_id']='installed_memory_capacity'
    path=case['root']/'broken.json';write_json(path,broken)
    first_dir=case['root']/'r1';first=build_draft_bundle(case['analyses'],path,first_dir)
    assert first['blocking_issues']
    issue={'issue_id':'scope_1','review_id':'observation:d00/o3','description':'장착량과 지원량 혼합','state':'open'}
    first_review=make_review(first_dir,findings=[issue],fail_ids=['observation:d00/o3'])
    first_review_path=case['root']/'r1_review.json';write_json(first_review_path,first_review.model_dump())
    assert not check_draft_bundle(first_dir,first_review_path)[1]['ready_for_offline_approval']
    fixed=copy.deepcopy(case['proposal']);fixed['revision']='fixture_r2'
    fixed['parent_draft_sha256']=sha((first_dir/'draft.json').read_bytes());fixed['change_notes']='지원량 매핑 수정'
    fixed_path=case['root']/'fixed.json';write_json(fixed_path,fixed)
    second_dir=case['root']/'r2';second=build_draft_bundle(case['analyses'],fixed_path,second_dir,
        previous_bundle=first_dir,previous_review_path=first_review_path)
    assert second['blocking_issues']==[]
    assert not check_draft_bundle(second_dir,first_review_path)[1]['ready_for_offline_approval']
    dropped=make_review(second_dir,previous_hash=sha(first_review_path.read_bytes()))
    dropped_path=case['root']/'dropped.json';write_json(dropped_path,dropped.model_dump())
    assert any('dropped' in e for e in check_draft_bundle(second_dir,dropped_path)[1]['blocking_issues'])
    issue.update(state='resolved',resolution='지원량 속성으로 재연결',resolved_in_revision='fixture_r2')
    resolved=make_review(second_dir,findings=[issue],previous_hash=sha(first_review_path.read_bytes()))
    resolved_path=case['root']/'resolved.json';write_json(resolved_path,resolved.model_dump())
    assert check_draft_bundle(second_dir,resolved_path)[1]['ready_for_offline_approval']


@pytest.mark.parametrize('tamper',['draft','source','input','review_coverage'])
def test_final_check_recomputes_inputs_and_rejects_missing_review(case,tamper):
    out=case['root']/'draft';build_draft_bundle(case['analyses'],case['proposal_path'],out)
    review=make_review(out);path=case['root']/'review.json';write_json(path,review.model_dump())
    if tamper=='review_coverage':
        review.checks.pop();path.write_text(review.model_dump_json())
        assert not check_draft_bundle(out,path)[1]['ready_for_offline_approval'];return
    if tamper=='draft':
        draft=json.loads((out/'draft.json').read_text());draft['catalogue']['attributes'][0]['name']='위조 수정'
        (out/'draft.json').write_text(json.dumps(draft))
    if tamper=='source':
        entry=json.loads((Path(case['analyses'].prepared_batch)/'batch.json').read_text())['documents'][0]
        (Path(case['analyses'].prepared_batch)/entry['native_file']).write_text('{}')
    if tamper=='input':(out/'consolidation.json').write_text('{}')
    with pytest.raises(ValueError):check_draft_bundle(out,path)


def test_independent_cli_and_no_overwrite(case):
    request=case['root']/'analysis_request.json';write_json(request,case['analyses'].model_dump())
    out=case['root']/'cli_draft'
    command=[sys.executable,'-m',MODULE,'build','--request',str(request),'--proposal',str(case['proposal_path']),'--output-dir',str(out)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert subprocess.run(command,capture_output=True,text=True).returncode==2
    review_path=case['root']/'cli_review.json';write_json(review_path,make_review(out).model_dump())
    report=case['root']/'final_check.json'
    command=[sys.executable,'-m',MODULE,'check','--draft-dir',str(out),'--review',str(review_path),'--output',str(report)]
    assert subprocess.run(command,capture_output=True,text=True).returncode==0
    assert json.loads(report.read_text())['ready_for_offline_approval']
    approved=case['root']/'fixture_approved.json'
    command=[sys.executable,'-m',MODULE,'approve','--draft-dir',str(out),'--review',str(review_path),'--output',str(approved),
             '--reviewer','synthetic_fixture','--authorization-note','SYNTHETIC_TEST_ONLY']
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(approved.read_text())['published'] is False


def test_next_batch_reuses_approved_definitions_and_rejects_repeats(case,tmp_path):
    out=case['root']/'draft';build_draft_bundle(case['analyses'],case['proposal_path'],out)
    review=make_review(out);path=case['root']/'review.json';write_json(path,review.model_dump())
    draft,check,*_=check_draft_bundle(out,path)
    approved=approve_offline_dictionary(draft,review,draft_sha256=check['draft_sha256'],review_sha256=sha(path.read_bytes()),
        reviewer_label='fixture',authorization_note='SYNTHETIC_TEST_ONLY')
    base=tmp_path/'base.json';write_json(base,approved)
    next_case=make_case(tmp_path/'next',start=10)
    request=next_case['analyses'].model_copy(update={'approved_base_path':str(base)})
    p=copy.deepcopy(next_case['proposal']);p.update(component_types=[],attributes=[],base_dictionary_sha256=sha(base.read_bytes()))
    p['alias_additions']=[{'target_kind':'attribute','target_id':'installed_memory_capacity',
                          'alias':{'expression':'Memory','context':'시스템 메모리의 실제 장착 용량 문맥',
                                   'evidence':next_case['discoveries']['d10']['observations'][0]['evidence']}}]
    prop_path=tmp_path/'next.json';write_json(prop_path,p)
    next_draft=build_draft_bundle(request,prop_path,tmp_path/'next_draft')
    assert next_draft['blocking_issues']==[] and len(next_draft['catalogue']['attributes'])==4
    assert len(next_draft['source_notices'])==20
    assert next_draft['catalogue']['attributes'][0]['aliases'][0]['expression']=='Memory'
    assert sha(base.read_bytes())==p['base_dictionary_sha256']
    repeated=case['analyses'].model_copy(update={'approved_base_path':str(base)})
    with pytest.raises(ValueError,match='repeats'):build_draft_bundle(repeated,prop_path,tmp_path/'repeated')


def test_extraction_has_no_standard_attribute_id(case):
    proposal=copy.deepcopy(case['discoveries']['d00'])
    proposal['observations'][0]['attribute_id']='forced_existing_attribute'
    with pytest.raises(ValueError,match='Extra inputs'):DiscoveryProposal.model_validate(proposal)


def test_failed_check_cannot_be_approved(case):
    out=case['root']/'draft';build_draft_bundle(case['analyses'],case['proposal_path'],out)
    review=make_review(out,fail_ids=['dictionary:duplicate_meanings'])
    with pytest.raises(ValueError,match='final review must pass'):
        approve_offline_dictionary(json.loads((out/'draft.json').read_text()),review,
            draft_sha256=sha((out/'draft.json').read_bytes()),review_sha256='a'*64,
            reviewer_label='fixture',authorization_note='SYNTHETIC_TEST_ONLY')


def test_unreadable_regions_are_explicit_and_block_when_deferred(case):
    doc_id='d00'
    native=json.loads(Path(case['request'].documents[0].native_path).read_text())
    native['blocks'].append({'type':'image','text':'image.bmp'})
    raw=json.dumps(native).encode()
    document=build_document_evidence(native,document_id=doc_id,parse_run_id='fixture',native_sha256=sha(raw))
    c=CompositionProposal.model_validate(case['compositions'][doc_id]);c.native_sha256=sha(raw)
    checksum=sha(c.model_dump_json().encode())
    d=DiscoveryProposal.model_validate(case['discoveries'][doc_id]);d.native_sha256=sha(raw);d.composition_sha256=checksum
    assert 'incomplete_unreadable_coverage' in validate_discovery(d,c,document,composition_sha256=checksum)
    from teoria_pipelines.domains.public_procurement.specification_intelligence.requirement_discovery import UnreadableCoverage
    d.unreadable_coverage=[UnreadableCoverage(native_ref='/blocks/7',decision='deferred',reason='OCR 제외로 내용 미확인',evidence=d.observations[0].evidence)]
    assert any('deferred_unreadable' in e for e in validate_discovery(d,c,document,composition_sha256=checksum))


def test_open_semantic_labels_are_not_forced_to_match_literal_ids(case):
    row=case['analyses'].documents[0]
    p=Path(row.discovery_path); discovery=json.loads(p.read_text())
    discovery['observations'][0]['meaning']['property_kind']='installed_ram_size_candidate'
    p.write_text(json.dumps(discovery,ensure_ascii=False))
    draft=build_draft_bundle(case['analyses'],case['proposal_path'],case['root']/'semantic_labels')
    assert draft['blocking_issues']==[]
    assert 'observation:d00/o2' in draft['required_review_ids']
    assert draft['semantic_review_status']=='pending'


def test_partially_extracted_cell_preserves_observations_and_blocks_approval(case):
    row=case['analyses'].documents[0]
    path=Path(row.discovery_path);discovery=json.loads(path.read_text())
    coverage=next(c for c in discovery['coverage'] if c['observation_ids'])
    coverage['decision']='partially_observed'
    coverage['reason']='같은 셀에 아직 원자화하지 않은 조건이 남음'
    path.write_text(json.dumps(discovery,ensure_ascii=False))
    draft=build_draft_bundle(case['analyses'],case['proposal_path'],case['root']/'partial_cell')
    assert any('deferred_text' in e for e in draft['blocking_issues'])
    assert not any('coverage_observation_mismatch' in e for e in draft['blocking_issues'])
    assert len(draft['requirements'])==40


def test_numeric_validation_does_not_join_ddr_generation_and_capacity(case):
    doc_id='d00';c=CompositionProposal.model_validate(case['compositions'][doc_id])
    d=DiscoveryProposal.model_validate(case['discoveries'][doc_id])
    raw=Path(case['request'].documents[0].native_path).read_bytes();native=json.loads(raw)
    native['blocks'][2]['text']='DDR5 16GB 이상 장착'
    raw=json.dumps(native).encode();document=build_document_evidence(native,document_id=doc_id,parse_run_id='fixture',native_sha256=sha(raw))
    c.native_sha256=sha(raw);d.native_sha256=sha(raw);d.composition_sha256=sha(c.model_dump_json().encode())
    d.observations[0].raw_text='DDR5 16GB 이상 장착';d.observations[0].raw_attribute=None
    d.observations[0].evidence[0].quote='DDR5 16GB 이상 장착'
    errors=validate_discovery(d,c,document,composition_sha256=d.composition_sha256)
    assert not any('numeric_value_not_exact' in e for e in errors)
    d.observations[0].value_text='1'
    assert any('numeric_value_not_exact' in e for e in validate_discovery(d,c,document,composition_sha256=d.composition_sha256))


def test_work_requirement_cannot_be_registered_as_product_attribute(case):
    path=Path(case['analyses'].documents[0].discovery_path)
    discovery=json.loads(path.read_text())
    discovery['observations'][0]['kind']='operational_requirement'
    path.write_text(json.dumps(discovery,ensure_ascii=False))
    draft=build_draft_bundle(case['analyses'],case['proposal_path'],case['root']/'work_attribute')
    assert 'd00/o2:work_requirement_must_not_be_an_attribute' in draft['blocking_issues']
    proposal=copy.deepcopy(case['proposal'])
    proposal['decisions'][0].update(decision='EXCLUDE',attribute_id=None,reason='작업 조건은 원문 요구로 보존')
    pp=case['root']/'work_excluded.json';write_json(pp,proposal)
    draft=build_draft_bundle(case['analyses'],pp,case['root']/'work_excluded')
    assert draft['blocking_issues']==[]
    assert next(r for r in draft['requirements'] if r['observation_ref']=='d00/o2')['observation']['kind']=='operational_requirement'


def test_implicit_count_unit_is_not_invented(case):
    row=case['analyses'].documents[0];path=Path(row.discovery_path)
    discovery=json.loads(path.read_text());o=discovery['observations'][0]
    o['meaning'].update(definition='합성 문맥상 개수',dimension='count',measurement_basis='implicit_count')
    o['unit_raw']=None
    path.write_text(json.dumps(discovery,ensure_ascii=False))
    proposal=copy.deepcopy(case['proposal']);attribute=copy.deepcopy(proposal['attributes'][0])
    attribute.update(attribute_id='implicit_count',name='합성 개수',meaning=o['meaning'],canonical_unit='개',accepted_raw_units=['개'])
    proposal['attributes'].append(attribute);proposal['decisions'][0]['attribute_id']='implicit_count'
    pp=case['root']/'implicit_count.json';write_json(pp,proposal)
    draft=build_draft_bundle(case['analyses'],pp,case['root']/'implicit_count')
    assert draft['blocking_issues']==[]
    assert draft['requirements'][0]['observation']['unit_raw'] is None


def test_removed_duplicate_definition_still_requires_review_resolution(case):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.dictionary_review import validate_final_review
    out=case['root']/'review_removal';draft=build_draft_bundle(case['analyses'],case['proposal_path'],out)
    previous=make_review(out)
    # A removed duplicate was a review target in the preceding revision.
    previous_data=previous.model_dump()
    previous_data['findings']=[dict(issue_id='removed_duplicate',review_id='attribute:removed_duplicate',
        description='중복 정의를 제거해야 함',state='open')]
    previous=FinalReview.model_validate(previous_data)
    draft['parent_draft_sha256']=previous.draft_sha256;draft['revision']='fixture_r2'
    current=make_review(out,previous_hash='b'*64)
    data=current.model_dump();data['findings']=[dict(issue_id='removed_duplicate',review_id='attribute:removed_duplicate',
        description='중복 정의를 제거해야 함',state='resolved',resolution='중복 정의를 제거하고 관찰을 유지 정의에 연결',resolved_in_revision='fixture_r2')]
    result=validate_final_review(draft,FinalReview.model_validate(data),draft_sha256=current.draft_sha256,
        previous_review=previous,previous_review_sha256='b'*64)
    assert not result['ready_for_offline_approval']
    data['checks'].append(dict(review_id='attribute:removed_duplicate',verdict='PASS',notes='제거와 재연결 검토'))
    result=validate_final_review(draft,FinalReview.model_validate(data),draft_sha256=current.draft_sha256,
        previous_review=previous,previous_review_sha256='b'*64)
    assert result['ready_for_offline_approval']
