"""CLI-owned extraction evaluation cycles with frozen inputs and mandatory cleanup."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from teoria.features.specification_processing.evaluation_cases import EvaluationManifest,file_sha256,local_source,sample_documents,verify_document
from teoria.features.specification_processing.evaluation_scoring import compare_runs,score_extraction

MODULE='teoria.features.specification_processing.evaluation'
DEFAULT_STATE=Path('.artifacts/specification_improvement')
REPOSITORY_ROOT=(Path(__file__).resolve().parents[5])

PARSER_RUNTIME_CODE='''import hashlib,importlib.metadata,json,sys
from pathlib import Path
import kory_parser
root=Path(kory_parser.__file__).parent
digest=hashlib.sha256()
for path in sorted(root.rglob('*.py')):
 digest.update(path.relative_to(root).as_posix().encode());digest.update(b'\\0');digest.update(path.read_bytes());digest.update(b'\\0')
packages=sorted((d.metadata.get('Name',''),d.version) for d in importlib.metadata.distributions())
print(json.dumps({'available':True,'version':getattr(kory_parser,'__version__','unknown'),
 'source_sha256':digest.hexdigest(),'packages_sha256':hashlib.sha256(json.dumps(packages).encode()).hexdigest(),
 'python_version':sys.version}))
'''


class ParserRuntimeChanged(ValueError):
    """The baseline and candidate no longer use the same parser implementation."""


def _parser_runtime(parser_python):
    executable=parser_python or os.getenv('TEORIA_SPECIFICATION_PARSER_PYTHON') or sys.executable
    try:
        result=subprocess.run([executable,'-c',PARSER_RUNTIME_CODE],capture_output=True,timeout=30)
        if result.returncode:return {'available':False,'executable':executable,'error':'parser_probe_failed'}
        return {**json.loads(result.stdout),'executable':executable}
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return {'available':False,'executable':executable,'error':'parser_probe_failed'}


def _assert_parser_runtime(cycle,manifest):
    expected=cycle.get('parser_runtime')
    if expected is not None and _parser_runtime(manifest.parser_python)!=expected:
        raise ParserRuntimeChanged('parser runtime changed since prepare; use a stable parser installation')


def _json(path):return json.loads(Path(path).read_text())


def _write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)


@contextmanager
def _locked(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(directory,os.O_RDONLY)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX);yield
    finally:
        fcntl.flock(descriptor,fcntl.LOCK_UN);os.close(descriptor)


def _state(directory):
    path=Path(directory)/'state.json'
    return _json(path) if path.exists() else {'schema_version':1,'used':[],'cycles':{}}


def _save(directory,state):_write(Path(directory)/'state.json',state)


def _grader_revision():
    root=Path(__file__).parent
    return hashlib.sha256(b''.join((root/name).read_bytes() for name in ('evaluation.py','evaluation_cases.py','evaluation_scoring.py'))).hexdigest()


def _processor_revision():
    from teoria.features.specification_processing.flows import processor_revision
    return processor_revision()


def _workspace(cycle, *, allow_missing=False):
    path=Path(cycle['workspace'])
    if path.is_symlink() or path.parent.resolve()!=Path(tempfile.gettempdir()).resolve() or not path.name.startswith('teoria_specification_eval_'):
        raise ValueError('unsafe evaluation cleanup boundary')
    if allow_missing and not path.exists():
        return path
    marker=_json(path/'.owner.json')
    if marker!={'cycle_id':cycle['cycle_id'],'token':cycle['token']}:raise ValueError('evaluation workspace owner mismatch')
    return path


def _size(path):return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())

def _process_identity(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
        return None if fields[0]=='Z' else fields[19]
    except (FileNotFoundError,IndexError,ProcessLookupError):return None


def _controller():return {'pid':os.getpid(),'identity':_process_identity(os.getpid())}


def _running_elsewhere(cycle):
    controller=cycle.get('controller',{})
    return (cycle['status'] in {'running','finishing'} and controller.get('pid')!=os.getpid()
            and controller.get('identity') is not None
            and _process_identity(controller['pid'])==controller['identity'])


def _report(directory,state):
    lines=['# 규격서 추출 개선 평가','', '실제 공통 추출 Task 01–05를 평가한다. 표준화·운영 DB 연동 평가는 포함하지 않는다.',
           '사례 점수는 고정된 원문 사례에 대한 일치이며 전체 문서 재현율·독립 정답 정확도가 아니다.','']
    for cycle_id,cycle in state['cycles'].items():
        lines.extend([f'## {cycle_id}','',f"- 상태: {cycle['status']} / 목적: {cycle.get('purpose','extraction_improvement')}",f"- 샘플: {cycle['sampling']}",
                      f"- 평가 계약: v{cycle.get('case_contract_version',1)} (서로 다른 계약의 점수는 개선량으로 비교하지 않음)",
                      f"- 판정: {cycle.get('comparison',{}).get('decision','pending')}",
                      f"- 사유: {cycle.get('comparison',{}).get('reasons',[])}",f"- 정리: {cycle.get('cleanup',{'status':'pending'})}"])
        for variant,summary in cycle.get('results',{}).items():
            for split,value in summary.items():
                lines.append(f"- {variant}/{split}: {value['metrics']} / {value.get('elapsed_seconds','?')}초")
        for finding in cycle.get('review_findings',[]):
            lines.append(f"- 확인 근거 {finding['document_id']}: {finding['grader_issue']}")
        if cycle.get('cycle_outcome_note'):
            lines.extend(['',cycle['cycle_outcome_note']])
        lines.append('')
    temporary=Path(directory,'index.md.tmp')
    temporary.write_text('\n'.join(lines)+'\n')
    temporary.replace(Path(directory,'index.md'))

def _persist_finished(directory,state,cycle):
    for _ in range(3):
        _save(directory,state);_report(directory,state)
        retained=sum((Path(directory)/name).stat().st_size for name in ('state.json','index.md'))
        if cycle['cleanup'].get('retained_bytes')==retained:break
        cycle['cleanup']['retained_bytes']=retained
    _save(directory,state);_report(directory,state)


def prepare_cycle(manifest_path,directory=DEFAULT_STATE):
    manifest=EvaluationManifest.model_validate(_json(manifest_path))
    for document in manifest.documents+manifest.regression_documents:
        verify_document(document,allow_unclassified=manifest.selection_mode=='fixed_sources')
    parser_runtime=_parser_runtime(manifest.parser_python)
    with _locked(directory):
        state=_state(directory)
        if manifest.cycle_id in state['cycles']:raise ValueError('cycle_id already exists')
        if any(c.get('cleanup',{}).get('status')!='complete' for c in state['cycles'].values()):
            raise ValueError('finish or abort the pending cycle before preparing another')
        if manifest.replay_of:
            parent=state['cycles'].get(manifest.replay_of)
            if parent is None or parent.get('cleanup',{}).get('status')!='complete':
                raise ValueError('calibration replay requires a completed prior cycle')
            original={d['document_id']:d for d in parent['frozen_documents']}
            supplied=manifest.documents+manifest.regression_documents
            for d in supplied:
                old=original.get(d.document_id)
                if old is None or (d.sha256,d.notice_number,d.classification_code)!=(old['sha256'],old['notice_number'],old['classification_code']):
                    raise ValueError('calibration replay may not change source identities')
            selected={d.document_id for d in supplied}
            splits={k:[i for i in ids if i in selected] for k,ids in parent['sampling']['splits'].items()}
            if set(splits['regression'])!={d.document_id for d in manifest.regression_documents}:
                raise ValueError('calibration replay may not move documents between splits')
            for name in ('model','parser_python','concurrency','model_concurrency','model_timeout_seconds'):
                if getattr(manifest,name)!=parent['settings'][name]:raise ValueError('calibration replay must retain execution settings')
            seed=parent['sampling']['seed']
            if manifest.seed is not None and manifest.seed!=seed:raise ValueError('calibration replay must retain the seed')
            aliases=[]
            sampling={'freshness':'exposed_calibration_replay','replay_of':manifest.replay_of,
                      'sampled_documents':len(manifest.documents),'independent_groups':None}
        else:
            seed=manifest.seed if manifest.seed is not None else secrets.randbits(63)
            splits,aliases,sampling=sample_documents(manifest,state,seed)
        if not splits['development']:raise ValueError('no eligible documents after exclusions')
        selected=set(sum(splits.values(),[]))
        manifest.documents=[d for d in manifest.documents if d.document_id in selected]
        if sum(len(d.entities)+len(d.relations)+len(d.requirements) for d in manifest.documents+manifest.regression_documents)>1000:
            raise ValueError('keep the frozen evaluation corpus under 1000 compact cases')
        manifest.seed=seed
        workspace=Path(tempfile.mkdtemp(prefix='teoria_specification_eval_'))
        cycle={'cycle_id':manifest.cycle_id,'token':secrets.token_hex(16),'workspace':str(workspace),
               'status':'prepared','sampling':{**sampling,'seed':seed,'splits':splits},'results':{},
               'purpose':manifest.purpose,'case_contract_version':manifest.case_contract_version,
               'baseline_revision':_processor_revision(),'grader_revision':_grader_revision(),
               'parser_runtime':parser_runtime,
               'cleanup':{'status':'pending'},'created_at':time.time()}
        try:
            _write(workspace/'.owner.json',{'cycle_id':manifest.cycle_id,'token':cycle['token']})
            frozen=manifest.model_dump(mode='json');_write(workspace/'manifest.json',frozen)
            cycle['manifest_sha256']=file_sha256(workspace/'manifest.json')
            cycle['input_manifest']={'path':str(Path(manifest_path).resolve()),'sha256':file_sha256(Path(manifest_path))}
            cycle['frozen_documents']=[d.model_dump(mode='json') for d in manifest.documents+manifest.regression_documents]
            cycle['settings']={k:frozen[k] for k in ('classification_code','parser_python','model','concurrency','model_concurrency','model_timeout_seconds','run_timeout_seconds')}
            for doc in aliases:
                state['used'].append({k:getattr(doc,k) for k in ('document_id','notice_number','sha256','template_family')})
            state['cycles'][manifest.cycle_id]=cycle;_save(directory,state);_report(directory,state)
        except BaseException:
            shutil.rmtree(workspace);raise
    return {'cycle_id':manifest.cycle_id,'workspace':str(workspace),'sampling':cycle['sampling']}


def _load_cycle(directory,cycle_id):
    state=_state(directory);cycle=state['cycles'][cycle_id]
    if cycle.get('cleanup',{}).get('status')=='complete':raise ValueError('cycle artifacts have been cleaned')
    workspace=_workspace(cycle)
    if file_sha256(workspace/'manifest.json')!=cycle['manifest_sha256']:raise ValueError('frozen manifest changed')
    if _grader_revision()!=cycle['grader_revision']:raise ValueError('frozen evaluator changed during cycle')
    manifest=EvaluationManifest.model_validate(_json(workspace/'manifest.json'))
    for document in manifest.documents+manifest.regression_documents:
        verify_document(document,allow_unclassified=manifest.selection_mode=='fixed_sources')
    return state,cycle,workspace,manifest


async def _launch(argv,*,cwd,env,timeout,pid_file=None):
    process=await asyncio.create_subprocess_exec(*argv,cwd=cwd,env=env,stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,start_new_session=True)
    try:
        if pid_file is not None:
            await asyncio.to_thread(_write,pid_file,{'pid':process.pid,'identity':_process_identity(process.pid)})
        stdout,stderr=await asyncio.wait_for(process.communicate(),timeout)
    except BaseException:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:await asyncio.wait_for(process.communicate(),15)
        except TimeoutError:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            await process.communicate()
        raise
    return process.returncode,stdout,stderr


async def _execute(request,run_dir,manifest):
    await asyncio.to_thread(_write,run_dir/'request.json',request)
    env=os.environ.copy()
    for key in list(env):
        if key.startswith('PREFECT_') or key=='TEORIA_PIPELINE_DATA_DATABASE_URL':env.pop(key,None)
    env.update({'PREFECT_HOME':str(run_dir/'prefect'),'PREFECT_SERVER_ANALYTICS_ENABLED':'false',
                'PREFECT_RESULTS_PERSIST_BY_DEFAULT':'false','PREFECT_SERVER_ALLOW_EPHEMERAL_MODE':'true'})
    started=time.monotonic()
    code,stdout,stderr=await _launch([sys.executable,'-m',MODULE,'worker',str(run_dir/'request.json')],
        cwd=REPOSITORY_ROOT,env=env,timeout=manifest.run_timeout_seconds,pid_file=run_dir/'worker_pid.json')
    await asyncio.to_thread((run_dir/'executor.log').write_bytes,stdout+b'\n'+stderr)
    if code:raise RuntimeError('extraction evaluation worker failed')
    extracted=run_dir/'objects/specification_processing'/request['run_id']/'extracted.json'
    corpus=await asyncio.to_thread(_json,extracted)
    corpus['_evaluation_usage']=await asyncio.to_thread(_usage,run_dir/'processing')
    return corpus,time.monotonic()-started


def _usage(directory):
    receipts=list(directory.rglob('*.receipt.json'))
    if not receipts:return {'available':False}
    tokens={'input_tokens':0,'cached_input_tokens':0,'output_tokens':0}
    for receipt in receipts:
        for event in _json(receipt).get('usage',[]):
            for key in tokens:tokens[key]+=event.get('usage',{}).get(key,0)
    return {'available':True,'model_calls':len(receipts),**tokens}


async def run_variant(cycle_id,variant,directory=DEFAULT_STATE):
    if variant not in {'baseline','candidate'}:raise ValueError('unknown evaluation variant')
    def reserve():
        with _locked(directory):
            state,cycle,workspace,manifest=_load_cycle(directory,cycle_id)
            if cycle['status'] in {'running','finishing'}:raise ValueError('cycle already running')
            if variant in cycle.get('completed_variants',[]):raise ValueError('variant already frozen')
            if manifest.purpose=='grader_calibration' and variant!='baseline':
                raise ValueError('grader calibration records a baseline, not an extraction candidate')
            revision=_processor_revision()
            if variant=='baseline' and revision!=cycle['baseline_revision']:raise ValueError('baseline code changed after prepare')
            if variant=='candidate' and 'baseline' not in cycle.get('completed_variants',[]):raise ValueError('run baseline before changing code')
            cycle['status']='running';cycle['controller']=_controller();cycle[variant+'_revision']=revision
            _save(directory,state)
            return cycle,workspace,manifest,revision
    cycle,workspace,manifest,revision=await asyncio.to_thread(reserve)
    try:
        documents={d.document_id:d for d in manifest.documents+manifest.regression_documents}
        summaries={};score_hashes={}
        for split,ids in cycle['sampling']['splits'].items():
            if not ids:continue
            await asyncio.to_thread(_assert_parser_runtime,cycle,manifest)
            run_dir=workspace/variant/split
            await asyncio.to_thread(run_dir.mkdir,parents=True,exist_ok=False)
            run_id='eval_'+hashlib.sha256(f'{cycle_id}:{variant}:{split}'.encode()).hexdigest()[:40]
            request={'run_id':run_id,'mode':'standard_management',
                     'classification_code':manifest.classification_code,'artifact_root':(run_dir/'objects').as_uri(),
                     'documents':[{k:v for k,v in documents[i].model_dump(mode='json').items()
                        if k in {'document_id','notice_number','source_uri','filename','sha256'}} for i in ids],
                     **{k:getattr(manifest,k) for k in ('parser_python','model','concurrency','model_concurrency','model_timeout_seconds')}}
            corpus,elapsed=await _execute(request,run_dir,manifest)
            await asyncio.to_thread(_assert_parser_runtime,cycle,manifest)
            summary=score_extraction(corpus,[documents[i] for i in ids]);summary['elapsed_seconds']=round(elapsed,3)
            summary['usage']=corpus.get('_evaluation_usage',{'available':False})
            summaries[split]=summary
            await asyncio.to_thread(_write,run_dir/'score.json',summary)
            score_hashes[split]=await asyncio.to_thread(file_sha256,run_dir/'score.json')
            if _processor_revision()!=revision:raise ValueError('processor changed while evaluation was running')
        def complete():
            with _locked(directory):
                state=_state(directory);item=state['cycles'][cycle_id]
                item['status']=variant+'_complete';item.setdefault('completed_variants',[]).append(variant)
                # Keep validation scores closed until candidate code is frozen and run.
                item.setdefault('results',{})[variant]={k:v for k,v in summaries.items() if k!='validation'}
                item.setdefault('score_hashes',{})[variant]=score_hashes
                _save(directory,state);_report(directory,state)
        await asyncio.to_thread(complete)
        return {'cycle_id':cycle_id,'variant':variant,'splits':list(summaries),'workspace':str(workspace),
                'development':summaries.get('development'),'validation':'closed_until_finish'}
    except BaseException as exc:
        await asyncio.shield(asyncio.to_thread(abort_cycle,cycle_id,directory,type(exc).__name__))
        raise


def _cleanup(cycle):
    workspace=_workspace(cycle,allow_missing=True);size=_size(workspace)
    if _running_elsewhere(cycle):raise ValueError('interrupt the active evaluation before aborting it')
    # A hard-killed controller may leave its worker alive. Signal only recorded, unreused process IDs.
    for path in workspace.rglob('worker_pid.json'):
        if path.is_symlink():continue
        worker=_json(path);pid=worker['pid'];identity=worker.get('identity')
        if identity is None or _process_identity(pid)!=identity:continue
        try:os.killpg(pid,signal.SIGTERM)
        except ProcessLookupError:continue
        deadline=time.monotonic()+15
        while _process_identity(pid)==identity and time.monotonic()<deadline:time.sleep(0.1)
        if _process_identity(pid)==identity:raise ValueError('evaluation worker has not terminated; cleanup remains pending')
    if workspace.exists():shutil.rmtree(workspace)
    cycle['cleanup']={'status':'complete','removed_bytes':size,'retained_bytes':0}
    cycle.pop('workspace',None);cycle.pop('token',None)


def abort_cycle(cycle_id,directory=DEFAULT_STATE,reason='aborted'):
    with _locked(directory):
        state=_state(directory);cycle=state['cycles'][cycle_id]
        if cycle.get('cleanup',{}).get('status')=='complete':return cycle['cleanup']
        if _running_elsewhere(cycle):raise ValueError('interrupt the active evaluation before aborting it')
        cycle['status']='aborted';cycle['comparison']={'decision':'inconclusive','reasons':[reason]}
        try:_cleanup(cycle)
        finally:_persist_finished(directory,state,cycle)
        return cycle['cleanup']


async def finish_cycle(cycle_id,directory=DEFAULT_STATE):
    busy=False
    try:
        state,cycle,workspace,manifest=await asyncio.to_thread(_load_cycle,directory,cycle_id)
        busy=cycle['status'] in {'running','finishing'}
        if busy:raise ValueError('cannot finish a running cycle')
        variants=('baseline',) if manifest.purpose=='grader_calibration' else ('baseline','candidate')
        revision_key='baseline_revision' if manifest.purpose=='grader_calibration' else 'candidate_revision'
        if set(cycle.get('completed_variants',[]))!=set(variants):raise ValueError('required variants must finish before comparison')
        if _processor_revision()!=cycle[revision_key]:raise ValueError('processor changed after evaluation')
        await asyncio.to_thread(_assert_parser_runtime,cycle,manifest)
        for variant in variants:
            for split,digest in cycle['score_hashes'][variant].items():
                if await asyncio.to_thread(file_sha256,workspace/variant/split/'score.json')!=digest:
                    raise ValueError('frozen evaluation score changed')
        results={variant:{split:await asyncio.to_thread(_json,workspace/variant/split/'score.json')
                         for split,ids in cycle['sampling']['splits'].items() if ids} for variant in variants}
        def reserve_finish():
            with _locked(directory):
                current=_state(directory);item=current['cycles'][cycle_id]
                if item['status'] in {'running','finishing'}:raise ValueError('cycle already running')
                item['status']='finishing';item['controller']=_controller();_save(directory,current)
        await asyncio.to_thread(reserve_finish)
        env=os.environ.copy()
        code,stdout,stderr=await _launch([sys.executable,'-m','pytest','backend/tests','-q'],
            cwd=REPOSITORY_ROOT,env=env,timeout=manifest.run_timeout_seconds)
        await asyncio.to_thread((workspace/'tests.log').write_bytes,stdout+b'\n'+stderr)
        if manifest.purpose=='grader_calibration':
            comparison={'decision':'baseline_recorded' if code==0 else 'rejected',
                        'reasons':['grader_calibration_only','no_extraction_improvement_claim']}
        else:
            comparison=compare_runs(results['baseline'],results['candidate'],code==0)
            if cycle['baseline_revision']==cycle['candidate_revision']:
                comparison={'decision':'inconclusive','reasons':['no_processor_change']}
            if any(results['baseline'][split]['parser_versions']!=results['candidate'][split]['parser_versions']
                   for split in results['baseline']):
                comparison={'decision':'inconclusive','reasons':['parser_version_changed']}
        if manifest.selection_mode=='fixed_sources' and comparison['decision']!='rejected':
            comparison={**comparison,'decision':'inconclusive',
                        'reasons':sorted(set(comparison['reasons']+['known_fixed_sources_not_independent_validation']))}
        if manifest.model is None:
            comparison={'decision':'inconclusive','reasons':['model_not_pinned']}
        if _processor_revision()!=cycle[revision_key]:comparison={'decision':'inconclusive','reasons':['processor_changed_during_tests']}
        await asyncio.to_thread(_assert_parser_runtime,cycle,manifest)
        def commit():
            with _locked(directory):
                current=_state(directory);item=current['cycles'][cycle_id]
                item.update({'results':results,'comparison':comparison,'status':'finished','pipeline_tests_exit_code':code})
                try:_cleanup(item)
                finally:_persist_finished(directory,current,item)
                return {'cycle_id':cycle_id,**comparison,'cleanup':item['cleanup']}
        return await asyncio.to_thread(commit)
    except BaseException as exc:
        if not busy:await asyncio.shield(asyncio.to_thread(abort_cycle,cycle_id,directory,type(exc).__name__))
        raise


async def worker(request_path):
    from teoria.features.specification_processing.flows import extraction_evaluation_flow
    current=asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,current.cancel)
    request=await asyncio.to_thread(_json,request_path)
    workspace=Path(request_path).parent/'processing'
    await asyncio.to_thread(workspace.mkdir)
    await extraction_evaluation_flow(request,str(workspace))


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='worker':raise SystemExit('internal evaluation worker entrypoint')
    asyncio.run(worker(Path(sys.argv[2])))
