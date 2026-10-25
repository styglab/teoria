"""Prefect orchestration: extraction → authoring API → pinned package → application."""
import asyncio
import hashlib
import json
from tempfile import TemporaryDirectory

from prefect import flow, task
from teoria_goods_normalization import NormalizationPackage, checksum
from teoria_goods_normalization.candidates import CandidateBundle
from .authoring_client import GoodsAuthoringClient
from .models import StandardWorkflow, StandardReference
from .standard_workflow_repository import StandardWorkflowRepository
from .storage.artifact_store import artifact_store, read_uri
from .standardization.profile_application import apply_profile
from .tasks import TASK_OPTIONS
from . import tasks


async def verified_json(reference):
    raw = await read_uri(reference['uri'])
    if hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('workflow artifact checksum mismatch')
    return json.loads(raw)


@task(name='09 승인 표준 패키지 저장', **TASK_OPTIONS)
async def export_package(revision_id, artifact_root, classification_code):
    async with GoodsAuthoringClient() as api:
        raw = await api.package(revision_id)
    package = NormalizationPackage.model_validate_json(raw)
    if str(package.profile_revision_id) != str(revision_id) or package.profile.classification_code != classification_code:
        raise ValueError('exported package identity or classification mismatch')
    digest = hashlib.sha256(raw).hexdigest()
    key = f'specification_processing/packages/{revision_id}/{digest}.json'
    async with artifact_store(artifact_root) as store:
        ref = await store.put(key, raw)
    return ref.model_dump()


@task(name='10 문맥별 표준 후보 묶기', **TASK_OPTIONS)
async def collect_candidates(extraction_ref, package_ref, artifact_root, workflow_key, phase):
    corpus = await verified_json(extraction_ref)
    package = NormalizationPackage.model_validate(await verified_json(package_ref))
    _, proposals = apply_profile(corpus, package, run_id=workflow_key)
    body = proposals['bundle']; body.pop('checksum')
    kinds = {'entity'} if phase == 'entities' else {'requirement','relation'}
    body['groups'] = [g for g in body['groups'] if g['context']['kind'] in kinds]
    bundle = CandidateBundle.model_validate({**body, 'checksum': checksum(body)})
    raw = (bundle.model_dump_json(indent=2) + '\n').encode()
    async with artifact_store(artifact_root) as store:
        ref = await store.put(f'specification_processing/workflows/{workflow_key}/{phase}/meaning_candidates.json', raw)
    return ref.model_dump()


@task(name='11 의미 판정·승인 상태 확인', **TASK_OPTIONS)
async def author_candidates(operation_id, base_revision_id, candidate_ref, model, auto_approve):
    bundle = CandidateBundle.model_validate(await verified_json(candidate_ref))
    payload = {'base_revision_id': str(base_revision_id), 'bundles': [bundle.model_dump(mode='json')],
        'model': model, 'version': operation_id, 'auto_approve': auto_approve, 'timeout': 300}
    deadline = asyncio.get_running_loop().time() + 3600
    async with GoodsAuthoringClient() as api:
        while True:
            result = await api.operation(operation_id, payload)
            if result['status'] != 'running': return result
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError('authoring operation is still running; resume the same workflow')
            await asyncio.sleep(3)


async def advance_workflow(request, repository, state, lease_id):
    from .flows import extract_documents, document_processing_flow
    workflow_key = 'wf_' + hashlib.sha256(request.workflow_id.encode()).hexdigest()[:28]
    extraction = request.extraction.model_copy(update={'run_id': workflow_key})
    async def checkpoint(status='running'):
        await repository.save(request.workflow_id, lease_id, state, status=status)
    if 'package_ref' not in state:
        state['package_ref'] = await export_package(str(request.base_profile_revision_id), extraction.artifact_root, extraction.classification_code)
        state['profile_revision_id'] = str(request.base_profile_revision_id)
        await checkpoint()
    with TemporaryDirectory(prefix='teoria_standard_workflow_') as workspace:
        if 'extraction_ref' in state:
            # The existing final Flow validates source IDs/hashes and reuses this checkpoint.
            await verified_json(state['extraction_ref'])
        else:
            state['extraction_ref'], _ = await extract_documents(extraction, workspace)
            await checkpoint()
        phases = state.setdefault('phases', {})
        for phase in ('entities','requirements'):
            stage = phases.setdefault(phase, {})
            if stage.get('completed'): continue
            if 'candidate_ref' not in stage:
                stage['base_revision_id'] = state['profile_revision_id']
                stage['candidate_ref'] = await collect_candidates(state['extraction_ref'], state['package_ref'],
                    extraction.artifact_root, workflow_key, phase)
                await checkpoint()
            operation_id = workflow_key + '_' + phase
            stage['operation'] = await author_candidates(operation_id, stage['base_revision_id'],
                stage['candidate_ref'], extraction.model, request.auto_approve)
            await checkpoint()
            status = stage['operation']['status']
            if status == 'awaiting_approval':
                result = {'workflow_id': request.workflow_id, 'status': 'awaiting_approval',
                    'phase': phase, 'operation': stage['operation']}
                state['result'] = result
                await checkpoint('awaiting_approval')
                return result
            if status not in {'approved','held'}:
                raise ValueError('authoring operation rejected or failed')
            if status == 'approved':
                revision_id = stage['operation']['profile_revision_id']
                state['package_ref'] = await export_package(revision_id, extraction.artifact_root, extraction.classification_code)
                state['profile_revision_id'] = revision_id
            stage['completed'] = True
            await checkpoint()
        final_request = extraction.model_copy(update={'mode': 'document_processing',
            'standard': StandardReference(uri=state['package_ref']['uri'], sha256=state['package_ref']['sha256']),
            'extraction_checkpoint': StandardReference(uri=state['extraction_ref']['uri'], sha256=state['extraction_ref']['sha256'])})
        final = await document_processing_flow(final_request.model_dump(mode='json'))
        result = {'workflow_id': request.workflow_id, 'status': final.status,
            'profile_revision_id': state['profile_revision_id'], 'final_run': final.model_dump(mode='json')}
        state['result'] = result
        await checkpoint('failed' if final.status=='failed' else 'completed')
        return result


@flow(name='procurement-standard-workflow', persist_result=False, log_prints=False)
async def standard_workflow_flow(manifest: dict):
    from .flows import processor_revision
    request = StandardWorkflow.model_validate(manifest)
    repository = StandardWorkflowRepository.from_environment()
    async with GoodsAuthoringClient() as api:
        authoring_url=api.base_url
    digest = checksum({'manifest': request.model_dump(mode='json'), 'processor': processor_revision(),
        'authoring_api': authoring_url})
    state, lease_id = await repository.claim(request.workflow_id, digest)
    if lease_id is None: return state['result']
    async def heartbeat():
        while True:
            await asyncio.sleep(45)
            await repository.renew(request.workflow_id, lease_id)
    worker = asyncio.create_task(advance_workflow(request, repository, state, lease_id))
    guard = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait([worker, guard], return_when=asyncio.FIRST_COMPLETED)
        if worker in done:return worker.result()
        if guard in done:
            guard.result()
            raise RuntimeError('workflow heartbeat ended unexpectedly')
    except BaseException as exc:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        try: await repository.save(request.workflow_id, lease_id, state, status='failed', error=type(exc).__name__)
        except Exception: pass
        raise
    finally:
        guard.cancel()
        await asyncio.gather(guard, return_exceptions=True)
