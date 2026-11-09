from copy import deepcopy
from pathlib import Path
import pytest
from teoria.features.specification_processing import evaluation as ev
from backend.tests.features.specification_processing.evaluation.test_cycles import frame,write_json,extracted


async def failed_assessment(frame,tmp_path,monkeypatch):
    path,data=frame;directory=tmp_path/'state'
    ev.prepare_cycle(path,directory);ev.abort_cycle('cycle_1',directory)
    selected=set(sum(ev._state(directory)['cycles']['cycle_1']['sampling']['splits'].values(),[]))
    manifest=deepcopy(data);manifest.update(cycle_id='assessment_1',purpose='quality_assessment',replay_of='cycle_1')
    manifest['documents']=[d for d in manifest['documents'] if d['document_id'] in selected]
    replay=write_json(tmp_path/'assessment.json',manifest);ev.prepare_cycle(replay,directory)
    async def execute(request,run_dir,m):
        if run_dir.name=='validation':raise ev.EvaluationWorkerError(1,b'',b'ValueError: fixture\n')
        docs={d.document_id:d for d in m.documents+m.regression_documents}
        return {'documents':[extracted(docs[d['document_id']]) for d in request['documents']]},0.01
    monkeypatch.setattr(ev,'_execute',execute)
    with pytest.raises(ev.EvaluationWorkerError):await ev.run_variant('assessment_1','baseline',directory)
    return directory,manifest


async def test_resume_skips_only_completed_documents_and_finishes_with_original_denominators(frame,tmp_path,monkeypatch):
    directory,manifest=await failed_assessment(frame,tmp_path,monkeypatch)
    old=ev._state(directory)['cycles']['assessment_1'];completed=old['sampling']['splits']['development']
    assert all(key in old['assessment_document_scores'] for key in completed)
    manifest.update(cycle_id='assessment_2',resume_from='assessment_1')
    prepared=ev.prepare_cycle(write_json(tmp_path/'resume.json',manifest),directory)
    executed=[]
    async def execute(request,run_dir,m):
        docs={d.document_id:d for d in m.documents+m.regression_documents}
        executed.extend(d['document_id'] for d in request['documents'])
        return {'documents':[extracted(docs[d['document_id']]) for d in request['documents']]},0.01
    async def tests(*args,**kwargs):return 0,b'passed',b''
    monkeypatch.setattr(ev,'_execute',execute);monkeypatch.setattr(ev,'_launch',tests)
    await ev.run_variant('assessment_2','baseline',directory)
    assert not set(executed)&set(completed)
    result=await ev.finish_cycle('assessment_2',directory)
    assert result['decision']=='assessment_recorded' and result['cleanup']['status']=='complete'
    final=ev._state(directory)['cycles']['assessment_2']
    assert final['results']['baseline']['development']['resumed_documents']==completed
    assert sum(s['metrics']['requirement_cases_total'] for s in final['results']['baseline'].values())==len(completed)+len(executed)
    assert not Path(prepared['workspace']).exists()


@pytest.mark.parametrize('change',['processor','parser','model','score'])
async def test_resume_refuses_incompatible_or_corrupt_results(frame,tmp_path,monkeypatch,change):
    directory,manifest=await failed_assessment(frame,tmp_path,monkeypatch)
    manifest.update(cycle_id='assessment_2',resume_from='assessment_1')
    if change=='processor':monkeypatch.setattr(ev,'_processor_revision',lambda:'different')
    elif change=='parser':monkeypatch.setattr(ev,'_parser_runtime',lambda p:{'changed':True})
    elif change=='model':manifest['model']='different'
    else:
        state=ev._state(directory)
        record=next(iter(state['cycles']['assessment_1']['assessment_document_scores'].values()))
        record['score']['metrics']['requirement_cases_found']=999
        ev._save(directory,state)
    with pytest.raises(ValueError):ev.prepare_cycle(write_json(tmp_path/'resume.json',manifest),directory)
