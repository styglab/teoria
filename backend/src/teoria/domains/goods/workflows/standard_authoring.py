"""Prefect orchestration: extraction → authoring API → pinned package → application."""
import asyncio
import hashlib
import json
from tempfile import TemporaryDirectory
from uuid import UUID

from prefect import flow, task
from teoria.domains.goods.normalization.contracts import NormalizationPackage, checksum
from teoria.domains.goods.normalization.contracts.candidates import CandidateBundle
from teoria.domains.goods.authoring_client import GoodsAuthoringClient
from teoria.domains.goods.contracts import StandardWorkflow, StandardReference
from teoria.domains.goods.workflows.standard_authoring_repository import StandardWorkflowRepository
from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store, read_uri
from teoria.domains.goods.normalization.candidates.proposals import (
    collect_semantic_candidates, plan_profile_expression_links,
)
from teoria.domains.goods.expression_links.expression_contracts import (
    OntologyDictionarySnapshot, expression_snapshot_for_publication,
    expression_review_state, require_expression_approval_policy,
)

from teoria.domains.goods.workflows.tasks import TASK_OPTIONS
from teoria.domains.goods.workflows import tasks


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
async def collect_candidates(extraction_ref, package_ref, artifact_root, workflow_key, phase, snapshot_ref):
    corpus = await verified_json(extraction_ref)
    package = NormalizationPackage.model_validate(await verified_json(package_ref))
    snapshot = OntologyDictionarySnapshot.model_validate(await verified_json(snapshot_ref))
    bundle = collect_semantic_candidates(corpus, package, snapshot, run_id=workflow_key, phase=phase)
    raw = (bundle.model_dump_json(indent=2) + '\n').encode()
    async with artifact_store(artifact_root) as store:
        ref = await store.put(f'specification_processing/workflows/{workflow_key}/{phase}/meaning_candidates.json', raw)
    return ref.model_dump()


@task(name='10a 원문 표현 등록·게시 연결 snapshot 고정', **TASK_OPTIONS)
async def export_expression_snapshot(extraction_ref, artifact_root, workflow_key, *, register=False, package_ref=None):
    from teoria.domains.goods.normalization.meaning_proposals.expression_candidates import register_corpus
    corpus = await verified_json(extraction_ref)
    async with GoodsAuthoringClient() as api:
        if register:
            # Source literal approval is distinct from Ontology meaning approval.
            documents = [{**d, 'classification_code': d.get('classification_code') or corpus.get('classification_code')}
                         for d in corpus['documents']]
            await register_corpus(api, {'documents': documents}, workflow_key + '_sources', auto_approve=True)
        snapshot = OntologyDictionarySnapshot.model_validate(await api.expression_snapshot())
    if package_ref is not None:
        package = NormalizationPackage.model_validate(await verified_json(package_ref))
        snapshot = expression_snapshot_for_publication(snapshot, package.profile.ontology)
    async with artifact_store(artifact_root) as store:
        ref = await store.put(f'specification_processing/workflows/{workflow_key}/snapshots/{snapshot.checksum}.json',
                              snapshot.model_dump_json().encode())
    return ref.model_dump(mode='json')


@task(name='12 표현 연결 제안·승인 상태 확인', **TASK_OPTIONS)
async def review_expression_links(candidate_ref, package_ref, extraction_ref, *, plan=None, auto_approve=False):
    """Approved profiles supply rules; expression equivalence needs its own review."""
    package = NormalizationPackage.model_validate(await verified_json(package_ref))
    bundle = CandidateBundle.model_validate(await verified_json(candidate_ref))
    reference = package.profile.ontology.model_dump(mode='json')
    require_expression_approval_policy(package.profile.ontology, auto_approve=auto_approve)
    async with GoodsAuthoringClient() as api:
        snapshot = OntologyDictionarySnapshot.model_validate(await api.expression_snapshot())
        if plan is None:
            corpus = await verified_json(extraction_ref)
            link_proposals = plan_profile_expression_links(bundle, package, snapshot, corpus)
            mapping_ids = []
            for proposal in link_proposals['proposals']:
                row = await api.dictionary_meaning('POST', '/mappings', proposal.model_dump(mode='json'))
                if auto_approve and row['status'] == 'draft':
                    row = await api.dictionary_meaning('POST', f'/mapping/{row["mapping_id"]}/decisions',
                        {'action': 'approve', 'rationale': '격리 평가 Ontology에서 명시적으로 요청한 연결 승인이다.'})
                mapping_ids.append(str(row['mapping_id']))
            plan = {'mapping_ids': sorted(set(mapping_ids)), 'unresolved': link_proposals['unresolved'], 'ontology': reference}
            snapshot = OntologyDictionarySnapshot.model_validate(await api.expression_snapshot())
        return expression_review_state(plan, snapshot, package.profile.ontology)


@task(name='11 의미 판정·승인 상태 확인', **TASK_OPTIONS)
async def author_candidates(operation_id, base_revision_id, candidate_ref, model, auto_approve, evaluation_ref=None):
    bundle = CandidateBundle.model_validate(await verified_json(candidate_ref))
    payload = {'base_revision_id': str(base_revision_id), 'bundles': [bundle.model_dump(mode='json')],
        'model': model, 'version': operation_id, 'auto_approve': auto_approve, 'timeout': 300}
    if evaluation_ref is not None:
        payload['evaluation'] = await verified_json(evaluation_ref.model_dump(mode='json'))
    deadline = asyncio.get_running_loop().time() + 3600
    async with GoodsAuthoringClient() as api:
        while True:
            result = await api.operation(operation_id, payload)
            if result['status'] != 'running': return result
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError('authoring operation is still running; resume the same workflow')
            await asyncio.sleep(3)


async def advance_workflow(request, repository, state, lease_id):
    from teoria.domains.goods.workflows.specifications import extract_documents, document_processing_flow
    workflow_key = 'wf_' + hashlib.sha256(request.workflow_id.encode()).hexdigest()[:28]
    extraction = request.extraction.model_copy(update={'run_id': workflow_key})
    from teoria.domains.goods.processor_revision import workflow_stage_versions
    versions = workflow_stage_versions()
    state['contract_version'] = 2
    state.setdefault('stage_versions', {})
    if 'extraction_ref' not in state:
        pinned = state['stage_versions'].setdefault('extraction', versions['extraction'])
        if pinned != versions['extraction']:
            raise ValueError('extraction code changed before completion; start a new workflow')
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
                stage['snapshot_ref'] = await export_expression_snapshot(state['extraction_ref'],
                    extraction.artifact_root, workflow_key, register=phase == 'entities')
                stage['semantic_version'] = versions['semantics']
                stage['base_revision_id'] = state['profile_revision_id']
                stage['candidate_ref'] = await collect_candidates(state['extraction_ref'], state['package_ref'],
                    extraction.artifact_root, workflow_key, phase, stage['snapshot_ref'])
                await checkpoint()
            if stage.get('semantic_version') != versions['semantics']:
                raise ValueError('semantic code changed for a pending review; start a new workflow')
            operation_id = workflow_key + '_' + phase
            stage['operation'] = await author_candidates(operation_id, stage['base_revision_id'],
                stage['candidate_ref'], extraction.model, request.auto_approve, request.semantic_evaluations.get(phase))
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
                stage['links'] = await review_expression_links(stage['candidate_ref'], state['package_ref'],
                    state['extraction_ref'], plan=stage.get('links'), auto_approve=request.auto_approve)
                if stage['links']['status'] == 'held':
                    raise ValueError('expression link review rejected or stale; start a new workflow')
                if stage['links']['status'] != 'ready':
                    result = {'workflow_id': request.workflow_id, 'status': 'awaiting_approval',
                        'phase': phase, 'review_stage': 'expression_links', 'review': stage['links'],
                        'profile_revision_id': state['profile_revision_id']}
                    state['result'] = result
                    await checkpoint('awaiting_approval')
                    return result
            stage['completed'] = True
            await checkpoint()
        if 'application_snapshot_ref' not in state:
            state['application_snapshot_ref'] = await export_expression_snapshot(state['extraction_ref'],
                extraction.artifact_root, workflow_key, package_ref=state['package_ref'])
            state['interpretation_revision_ids'] = [str(x) for x in (request.interpretation_revision_ids or [])]
            state['stage_versions']['application'] = versions['application']
            await checkpoint()
        elif (request.interpretation_revision_ids is not None
                and state['interpretation_revision_ids'] != [str(x) for x in request.interpretation_revision_ids]):
            raise ValueError('application approvals are pinned; start a new workflow to change them')
        if state['stage_versions']['application'] != versions['application']:
            raise ValueError('application code changed after inputs were pinned; start a new workflow')
        application_key = checksum({'profile': state['package_ref'], 'dictionary': state['application_snapshot_ref'],
            'interpretations': state['interpretation_revision_ids'], 'code': versions['application']})[:12]
        final_request = extraction.model_copy(update={'mode': 'document_processing',
            'run_id': workflow_key + '_apply_' + application_key,
            'dictionary_auto_approve': False, 'dictionary_meaning_auto_approve': False,
            'dictionary_standard': StandardReference(**{k:state['application_snapshot_ref'][k] for k in ('uri','sha256')}),
            'interpretation_revision_ids': [UUID(x) for x in state['interpretation_revision_ids']],
            'auto_approve_application_standard': False, 'auto_apply_source_literals': False,
            'standard': StandardReference(uri=state['package_ref']['uri'], sha256=state['package_ref']['sha256']),
            'extraction_checkpoint': StandardReference(uri=state['extraction_ref']['uri'], sha256=state['extraction_ref']['sha256'])})
        final = await document_processing_flow(final_request.model_dump(mode='json'))
        result = {'workflow_id': request.workflow_id, 'status': final.status,
            'profile_revision_id': state['profile_revision_id'], 'final_run': final.model_dump(mode='json'),
            'stage_versions': state['stage_versions'],
            'review_routes': [row for phase in phases.values() for row in phase.get('links', {}).get('unresolved', [])],
            'quality': {'extraction': final.summary.get('quality_evaluation', {'status': 'not_attached'}),
                        'ontology_decisions': {name: p.get('operation', {}).get('evaluation', {'status': 'not_evaluated'})
                                               for name,p in phases.items()},
                        'application': final.summary.get('quality', {})}}

        state['result'] = result
        await checkpoint('failed' if final.status=='failed' else 'completed')
        return result


@flow(name='procurement-standard-workflow', persist_result=False, log_prints=False)
async def standard_workflow_flow(manifest: dict):
    request = StandardWorkflow.model_validate(manifest)
    repository = StandardWorkflowRepository.from_environment()
    async with GoodsAuthoringClient() as api:
        authoring_url=api.base_url
    # Version the workflow contract, not every unrelated goods code edit.
    digest = checksum({'contract_version': 2,
        'manifest': request.model_dump(mode='json', exclude={'interpretation_revision_ids'}),
        'authoring_api': authoring_url})
    state, lease_id = await repository.claim(request.workflow_id, digest)
    if lease_id is None:
        if (request.interpretation_revision_ids is not None
                and state.get('interpretation_revision_ids', []) != [str(x) for x in request.interpretation_revision_ids]):
            raise ValueError('completed workflow has different interpretation approvals')
        return state['result']
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
