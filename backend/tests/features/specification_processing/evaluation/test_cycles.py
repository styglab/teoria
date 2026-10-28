import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from teoria.features.specification_processing import evaluation as ev
from teoria.features.specification_processing.evaluation_cases import EvaluationManifest,sample_documents,verify_document
from teoria.features.specification_processing.evaluation_scoring import score_extraction,compare_runs


def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False));return path


@pytest.fixture
def frame(tmp_path,monkeypatch):
    monkeypatch.setattr(ev,'_parser_runtime',lambda parser_python:{'available':True,'source_sha256':'fixture_source','packages_sha256':'fixture_packages'})
    docs=[]
    for i in range(7):
        source=tmp_path/f'doc_{i}.hwp';source.write_bytes(f'source original {i}'.encode())
        metadata=write_json(tmp_path/f'metadata_{i}.json',{'code':'4321150102','notice':f'N{i}'})
        docs.append({'document_id':f'doc_{i}','notice_number':f'N{i}','filename':source.name,'source_uri':source.as_uri(),
            'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'classification_code':'4321150102',
            'classification_evidence':{'path':str(metadata),'sha256':hashlib.sha256(metadata.read_bytes()).hexdigest(),
                'code_pointer':'/code','notice_pointer':'/notice'},'template_family':f'family_{i}',
            'requirements':[{'subjects':['CPU'],'value_raw':'16','unit_raw':'core','operator':'gte','source_text':'CPU 16core 이상'}]})
    data={'cycle_id':'cycle_1','model':'pinned_test_model','sample_size':4,'seed':42,'history_reviewed':True,
          'documents':docs[:6],'regression_documents':[docs[6]]}
    path=write_json(tmp_path/'manifest.json',data)
    yield path,data
    # Never leave evaluation workspaces after a failed assertion.
    for state_path in tmp_path.rglob('state.json'):
        state=json.loads(state_path.read_text())
        if 'cycles' not in state:continue
        for cycle_id,cycle in state['cycles'].items():
            if cycle.get('cleanup',{}).get('status')!='complete':ev.abort_cycle(cycle_id,state_path.parent)


def extracted(document,found=True):
    attribute={'id':'a','subject_ids':['cpu'],'property_key':'cores','value_raw':'16','unit_raw':'core','operator':'gte',
               'operator_raw':'이상','qualifiers_raw':[],'semantic_role':'requirement_candidate','semantic_scope':'per_component',
               'evidence':{'node_id':'n'}}
    return {'document_id':document.document_id,'source':{'sha256':document.sha256},
            'entities':[{'id':'cpu','name':'CPU','kind':'equipment','evidence':[{'node_id':'n'}]}],
            'relations':[],'attributes':[attribute] if found else [],
            'parsed_document':{'nodes':[{'node_id':'n','text':'CPU 16core 이상'}]},'extraction_status':'extracted'}


def test_seeded_sampling_is_order_independent_and_group_disjoint(frame):
    _,data=frame;data['documents'][1]['notice_number']='N0';data['documents'][2]['template_family']='family_0'
    manifest=EvaluationManifest.model_validate(data)
    one,_,_=sample_documents(manifest,{},42)
    shuffled=manifest.model_copy(update={'documents':list(reversed(manifest.documents))})
    two,_,_=sample_documents(shuffled,{},42)
    assert one==two
    first={d.document_id:d for d in manifest.documents}
    dev={first[i].notice_number for i in one['development']};val={first[i].notice_number for i in one['validation']}
    assert not dev&val
    assert not {first[i].template_family for i in one['development']}&{first[i].template_family for i in one['validation']}


def test_previous_hash_excludes_connected_alias_notices_and_templates(frame):
    _,data=frame;data['documents'][1]['sha256']=data['documents'][0]['sha256']
    data['documents'][2]['template_family']=data['documents'][1]['template_family']
    manifest=EvaluationManifest.model_validate(data)
    splits,aliases,_=sample_documents(manifest,{'used':[data['documents'][0]]},42)
    assert not {'doc_0','doc_1','doc_2'}&set(sum(splits.values(),[]))
    assert not {'doc_0','doc_1','doc_2'}&{d.document_id for d in aliases}


def test_metadata_cannot_assign_another_notice_classification(frame):
    _,data=frame;document=EvaluationManifest.model_validate(data).documents[0]
    verify_document(document)
    document.notice_number='unrelated_notice'
    with pytest.raises(ValueError,match='another notice'):verify_document(document)


def test_failed_extraction_stays_in_case_denominator(frame):
    _,data=frame;document=EvaluationManifest.model_validate(data).documents[0]
    result=score_extraction({'documents':[]},[document])
    assert result['metrics']['requirement_cases_total']==1
    assert result['metrics']['requirement_cases_found']==0
    assert result['metrics']['failed_documents']==1
    assert result['independent_gold'] is False


def test_matching_number_on_wrong_entity_is_not_a_correct_requirement(frame):
    _,data=frame;document=EvaluationManifest.model_validate(data).documents[0]
    actual=extracted(document);actual['entities'].append({'id':'ram','name':'RAM','kind':'equipment','evidence':[{'node_id':'n'}]})
    actual['attributes'][0]['subject_ids']=['ram']
    assert score_extraction({'documents':[actual]},[document])['metrics']['requirement_cases_found']==0


def test_no_labels_does_not_become_an_accuracy_measure(frame):
    _,data=frame;document=EvaluationManifest.model_validate(data).documents[0];document.requirements=[]
    summary=score_extraction({'documents':[extracted(document)]},[document])
    result=compare_runs({'development':summary},{'development':summary},True)
    assert result['decision']=='inconclusive'
    assert 'development:no_frozen_cases' in result['reasons']


async def test_lifecycle_freezes_before_after_and_deletes_every_bulky_result(frame,tmp_path,monkeypatch):
    path,data=frame;directory=tmp_path/'summary';revision=['baseline']
    monkeypatch.setattr(ev,'_processor_revision',lambda:revision[0])
    prepared=ev.prepare_cycle(path,directory);workspace=Path(prepared['workspace'])
    documents={d.document_id:d for d in EvaluationManifest.model_validate(data).documents+EvaluationManifest.model_validate(data).regression_documents}
    async def execute(request,run_dir,manifest):
        (run_dir/'bulky.json').write_bytes(b'x'*10000)
        return {'documents':[extracted(documents[d['document_id']],revision[0]=='candidate') for d in request['documents']]},1.0
    monkeypatch.setattr(ev,'_execute',execute)
    baseline=await ev.run_variant('cycle_1','baseline',directory)
    assert baseline['validation']=='closed_until_finish'
    assert 'validation' not in ev._state(directory)['cycles']['cycle_1']['results']['baseline']
    with pytest.raises(ValueError,match='already frozen'):await ev.run_variant('cycle_1','baseline',directory)
    revision[0]='candidate';await ev.run_variant('cycle_1','candidate',directory)
    async def passing_tests(*args,**kwargs):return 0,b'passed',b''
    monkeypatch.setattr(ev,'_launch',passing_tests)
    result=await ev.finish_cycle('cycle_1',directory)
    assert result['decision']=='accepted'
    assert result['cleanup']['removed_bytes']>=60000
    assert result['cleanup']['retained_bytes']>0 and not workspace.exists()
    assert sorted(p.name for p in directory.iterdir())==['index.md','state.json']
    assert len(ev._state(directory)['used'])==4
    assert all(Path(d['source_uri'].removeprefix('file://')).exists() for d in data['documents'])


@pytest.mark.parametrize('cancel',[False,True])
async def test_failure_and_cancellation_cleanup_before_return(frame,tmp_path,monkeypatch,cancel):
    path,_=frame;directory=tmp_path/'summary';prepared=ev.prepare_cycle(path,directory)
    async def fail(request,run_dir,manifest):
        (run_dir/'large.log').write_bytes(b'x'*5000)
        if cancel:raise asyncio.CancelledError()
        raise RuntimeError('injected execution failure')
    monkeypatch.setattr(ev,'_execute',fail)
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await ev.run_variant('cycle_1','baseline',directory)
    cycle=ev._state(directory)['cycles']['cycle_1']
    assert cycle['status']=='aborted' and cycle['cleanup']['status']=='complete'
    assert not Path(prepared['workspace']).exists()


def test_cleanup_refuses_an_input_directory(frame,tmp_path):
    path,_=frame;directory=tmp_path/'summary';ev.prepare_cycle(path,directory)
    state=ev._state(directory);cycle=state['cycles']['cycle_1'];original=cycle['workspace'];cycle['workspace']=str(tmp_path)
    ev._save(directory,state)
    with pytest.raises(ValueError,match='unsafe evaluation cleanup'):ev.abort_cycle('cycle_1',directory)
    assert path.exists()
    state=ev._state(directory);state['cycles']['cycle_1']['workspace']=original;ev._save(directory,state)
    ev.abort_cycle('cycle_1',directory)


def test_fixed_regression_is_excluded_from_the_random_pool(frame):
    _,data=frame
    data['documents'][0]['notice_number']=data['regression_documents'][0]['notice_number']
    splits,_,_=sample_documents(EvaluationManifest.model_validate(data),{},42)
    assert 'doc_0' not in splits['development']+splits['validation']
    assert splits['regression']==['doc_6']


async def test_source_change_at_finish_does_not_leave_bulk_results(frame,tmp_path):
    path,data=frame;directory=tmp_path/'summary';prepared=ev.prepare_cycle(path,directory)
    chosen=next(iter(ev._state(directory)['cycles']['cycle_1']['frozen_documents']))
    Path(chosen['source_uri'].removeprefix('file://')).write_bytes(b'changed original')
    with pytest.raises(ValueError,match='source checksum'):
        await ev.finish_cycle('cycle_1',directory)
    assert not Path(prepared['workspace']).exists()
    assert ev._state(directory)['cycles']['cycle_1']['cleanup']['status']=='complete'


async def test_native_subprocess_timeout_terminates_the_child():
    import os,sys
    with pytest.raises(TimeoutError):
        await ev._launch([sys.executable,'-c','import time; time.sleep(30)'],cwd=Path.cwd(),env=os.environ.copy(),timeout=0.05)


def test_scorer_checks_owner_and_relation_direction_without_changing_denominators(frame):
    _,data=frame;document=EvaluationManifest.model_validate(data).documents[0]
    from teoria.features.specification_processing.evaluation_cases import RelationCase
    document.requirements[0].owner='서버 A'
    document.relations=[RelationCase(source='CPU',target='서버 A',kind='component_of',source_text='CPU 16core 이상')]
    actual=extracted(document)
    actual['entities'].extend([{'id':'a','name':'서버 A','kind':'equipment','evidence':[]},
                               {'id':'b','name':'서버 B','kind':'equipment','evidence':[]}])
    actual['relations']=[{'source_id':'cpu','target_id':'b','kind':'component_of','evidence':[{'node_id':'n'}]}]
    wrong=score_extraction({'documents':[actual]},[document])
    assert wrong['metrics']['requirement_cases_found']==0 and wrong['metrics']['relation_cases_found']==0
    actual['relations'][0]['target_id']='a'
    correct=score_extraction({'documents':[actual]},[document])
    assert correct['metrics']['requirement_cases_found']==1 and correct['metrics']['relation_cases_found']==1
    actual['relations'][0]['source_id']='a';actual['relations'][0]['target_id']='cpu'
    reversed_=score_extraction({'documents':[actual]},[document])
    assert reversed_['metrics']['relation_cases_total']==1 and reversed_['metrics']['relation_cases_found']==0


def test_abort_cannot_delete_another_live_controller_workspace(frame,tmp_path,monkeypatch):
    path,_=frame;directory=tmp_path/'summary';prepared=ev.prepare_cycle(path,directory)
    state=ev._state(directory);cycle=state['cycles']['cycle_1']
    cycle['status']='running';cycle['controller']={'pid':987654,'identity':'live_start_time'};ev._save(directory,state)
    original=ev._process_identity
    monkeypatch.setattr(ev,'_process_identity',lambda pid:'live_start_time' if pid==987654 else original(pid))
    with pytest.raises(ValueError,match='active evaluation'):ev.abort_cycle('cycle_1',directory)
    assert Path(prepared['workspace']).exists()
    state=ev._state(directory);state['cycles']['cycle_1']['status']='baseline_complete';ev._save(directory,state)
    ev.abort_cycle('cycle_1',directory)


async def test_calibration_replay_preserves_source_split_history_and_cannot_be_promoted(frame,tmp_path,monkeypatch):
    path,data=frame;directory=tmp_path/'summary'
    parent=ev.prepare_cycle(path,directory);ev.abort_cycle('cycle_1',directory)
    saved=ev._state(directory);old=saved['cycles']['cycle_1'];selected=set(sum(old['sampling']['splits'].values(),[]))
    replay=deepcopy(data);replay.update({'cycle_id':'calibration_1','purpose':'grader_calibration','replay_of':'cycle_1','seed':None})
    replay['documents']=[d for d in replay['documents'] if d['document_id'] in selected]
    replay['documents'][0]['requirements'][0]['qualifiers_raw']=None
    replay_path=write_json(tmp_path/'replay.json',replay)
    prepared=ev.prepare_cycle(replay_path,directory)
    state=ev._state(directory)
    assert prepared['sampling']['splits']==old['sampling']['splits']
    assert prepared['sampling']['freshness']=='exposed_calibration_replay'
    assert state['used']==saved['used']
    docs={d.document_id:d for d in EvaluationManifest.model_validate(replay).documents+EvaluationManifest.model_validate(replay).regression_documents}
    async def execute(request,run_dir,manifest):return {'documents':[extracted(docs[d['document_id']]) for d in request['documents']]},1.0
    async def passing(*args,**kwargs):return 0,b'passed',b''
    monkeypatch.setattr(ev,'_execute',execute);monkeypatch.setattr(ev,'_launch',passing)
    with pytest.raises(ValueError,match='not an extraction candidate'):await ev.run_variant('calibration_1','candidate',directory)
    await ev.run_variant('calibration_1','baseline',directory)
    result=await ev.finish_cycle('calibration_1',directory)
    assert result['decision']=='baseline_recorded' and 'no_extraction_improvement_claim' in result['reasons']
    assert not Path(prepared['workspace']).exists()


def test_calibration_replay_cannot_replace_sources_or_reset_history(frame,tmp_path):
    path,data=frame;directory=tmp_path/'summary'
    ev.prepare_cycle(path,directory);ev.abort_cycle('cycle_1',directory)
    replay=deepcopy(data);replay.update({'cycle_id':'calibration_1','purpose':'grader_calibration','replay_of':'cycle_1','seed':None})
    old=ev._state(directory)['cycles']['cycle_1'];selected=set(sum(old['sampling']['splits'].values(),[]))
    replay['documents']=[d for d in replay['documents'] if d['document_id'] in selected]
    replay['documents'][0]['document_id']='replacement'
    with pytest.raises(ValueError,match='source identities'):
        ev.prepare_cycle(write_json(tmp_path/'replay.json',replay),directory)


def test_evaluator_changes_do_not_change_the_extraction_revision(tmp_path,monkeypatch):
    from teoria.features.specification_processing import flows
    (tmp_path/'flows.py').write_text('production_flow')
    (tmp_path/'evaluation_scoring.py').write_text('grader_v1')
    monkeypatch.setattr(flows,'__file__',str(tmp_path/'flows.py'))
    original=flows.processor_revision()
    (tmp_path/'evaluation_scoring.py').write_text('grader_v2')
    assert flows.processor_revision()==original
    (tmp_path/'flows.py').write_text('changed_production_flow')
    assert flows.processor_revision()!=original


@pytest.mark.parametrize('stage',['before_baseline','during_baseline','before_candidate','before_finish'])
async def test_parser_drift_aborts_without_continuing_invalid_comparison(frame,tmp_path,monkeypatch,stage):
    path,_=frame;directory=tmp_path/'parser_guard';profile={'available':True,'source_sha256':'old','packages_sha256':'fixed'}
    monkeypatch.setattr(ev,'_parser_runtime',lambda parser_python:dict(profile))
    revision=['baseline'];monkeypatch.setattr(ev,'_processor_revision',lambda:revision[0])
    calls=[]
    async def execute(request,run_dir,manifest):
        calls.append(request['run_id'])
        if stage=='during_baseline':profile['source_sha256']='changed_without_version_bump'
        docs={d.document_id:d for d in manifest.documents+manifest.regression_documents}
        return {'documents':[extracted(docs[d['document_id']]) for d in request['documents']]},0.01
    monkeypatch.setattr(ev,'_execute',execute)
    prepared=ev.prepare_cycle(path,directory)
    if stage in {'before_candidate','before_finish'}:
        await ev.run_variant('cycle_1','baseline',directory)
        revision[0]='candidate'
    if stage=='before_finish':await ev.run_variant('cycle_1','candidate',directory)
    if stage!='during_baseline':profile['packages_sha256']='changed_dependency_installation'
    previous_calls=len(calls)
    with pytest.raises(ev.ParserRuntimeChanged,match='parser runtime changed'):
        if stage=='before_finish':await ev.finish_cycle('cycle_1',directory)
        else:await ev.run_variant('cycle_1','candidate' if stage=='before_candidate' else 'baseline',directory)
    assert len(calls)==previous_calls+(stage=='during_baseline')
    state=json.loads((directory/'state.json').read_text());cycle=state['cycles']['cycle_1']
    assert cycle['comparison']['decision']=='inconclusive'
    assert cycle['comparison']['reasons']==['ParserRuntimeChanged']
    assert cycle['cleanup']['status']=='complete' and not Path(prepared['workspace']).exists()
    assert Path(cycle['frozen_documents'][0]['source_uri'].removeprefix('file://')).exists()


def test_parser_probe_detects_same_version_source_and_dependency_changes(tmp_path,monkeypatch):
    package=tmp_path/'kory_parser';package.mkdir();(package/'__init__.py').write_text('__version__="test_version"\n')
    helper=package/'helper.py';helper.write_text('VALUE=1\n')
    monkeypatch.setenv('PYTHONPATH',str(tmp_path))
    initial=ev._parser_runtime(None);assert initial['available']
    helper.write_text('VALUE=2\n')
    changed=ev._parser_runtime(None)
    assert initial['version']==changed['version'] and initial['source_sha256']!=changed['source_sha256']
    (package/'__pycache__').mkdir(exist_ok=True);(package/'__pycache__/irrelevant.pyc').write_bytes(b'cache')
    assert ev._parser_runtime(None)==changed
    metadata=tmp_path/'runtime_helper-1.dist-info';metadata.mkdir();(metadata/'METADATA').write_text('Name: runtime-helper\nVersion: 1\n')
    updated=ev._parser_runtime(None)
    assert updated['source_sha256']==changed['source_sha256']
    assert updated['packages_sha256']!=changed['packages_sha256']


def test_unavailable_parser_remains_explicit_without_leaking_process_output():
    profile=ev._parser_runtime('/bin/false')
    assert profile=={'available':False,'executable':'/bin/false','error':'parser_probe_failed'}


def test_unclassified_originals_require_explicit_fixed_source_mode(frame):
    _,data=frame
    for document in data['documents']+data['regression_documents']:
        for key in ('notice_number','classification_code','classification_evidence'):
            document.pop(key)
    with pytest.raises(ValueError,match='classified sampling requires'):
        EvaluationManifest.model_validate(data)
    data.update(selection_mode='fixed_sources',classification_code=None)
    manifest=EvaluationManifest.model_validate(data)
    for document in manifest.documents+manifest.regression_documents:
        with pytest.raises(ValueError,match='metadata is required'):
            verify_document(document)
        verify_document(document,allow_unclassified=True)
    splits,aliases,sampling=sample_documents(manifest,{'used':data['documents']},42)
    assert splits['development']==[d.document_id for d in manifest.documents]
    assert splits['validation']==[] and sampling['freshness']=='known_fixed_sources'
    assert sampling['sampled_documents']==0 and len(aliases)==7
    # Fixed known checks cannot silently acquire a claimed classification.
    data['classification_code']='4321150102'
    with pytest.raises(ValueError,match='explicitly absent'):
        EvaluationManifest.model_validate(data)


async def test_fixed_source_finish_never_claims_independent_acceptance(frame,tmp_path,monkeypatch):
    path,data=frame
    for document in data['documents']+data['regression_documents']:
        for key in ('notice_number','classification_code','classification_evidence'):document.pop(key)
    data.update(selection_mode='fixed_sources',classification_code=None)
    write_json(path,data);state_dir=tmp_path/'fixed_state'
    ev.prepare_cycle(path,state_dir)
    changed=False
    async def execute(request,run_dir,manifest):
        docs={d.document_id:d for d in manifest.documents+manifest.regression_documents}
        return {'documents':[extracted(docs[d['document_id']]) for d in request['documents']]},0.01
    monkeypatch.setattr(ev,'_execute',execute)
    await ev.run_variant('cycle_1','baseline',state_dir)
    monkeypatch.setattr(ev,'_processor_revision',lambda:'candidate')
    await ev.run_variant('cycle_1','candidate',state_dir)
    async def launch(*args,**kwargs):return 0,b'checks passed',b''
    monkeypatch.setattr(ev,'_launch',launch)
    result=await ev.finish_cycle('cycle_1',state_dir)
    assert result['decision']=='inconclusive'
    assert 'known_fixed_sources_not_independent_validation' in result['reasons']
    assert result['cleanup']['status']=='complete'


def test_failed_prepare_report_can_be_aborted_without_an_orphaned_cycle(frame,tmp_path,monkeypatch):
    path,_=frame;directory=tmp_path/'failed_prepare';original=ev._report
    def fail_report(*args):raise PermissionError('read-only existing report')
    monkeypatch.setattr(ev,'_report',fail_report)
    with pytest.raises(PermissionError):ev.prepare_cycle(path,directory)
    cycle=ev._state(directory)['cycles']['cycle_1']
    assert not Path(cycle['workspace']).exists()
    monkeypatch.setattr(ev,'_report',original)
    result=ev.abort_cycle('cycle_1',directory,'failed_preflight')
    assert result['status']=='complete' and result['removed_bytes']==0
