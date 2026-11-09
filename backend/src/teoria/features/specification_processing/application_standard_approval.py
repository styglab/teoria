"""Automatically pin usable extraction rules through the authenticated Admin API."""
import hashlib
from uuid import NAMESPACE_URL, uuid5

from prefect import task
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import approved_dictionary_snapshot, parse_dictionary_snapshot
from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
from teoria.features.specification_processing.storage.artifact_store import read_uri
from teoria.features.specification_processing.storage.run_repository import SpecificationRepository
from teoria.features.specification_processing.tasks import TASK_OPTIONS
from teoria.features.specification_processing.processing_quality import AutomaticApprovalLimits,automatic_approval_quality


@task(name='11 처리 기준 자동 승인·고정', **TASK_OPTIONS)
async def approve_application_standard(request, result):
    repository=SpecificationRepository.from_environment()
    quality=result.summary.get('quality')
    baseline=await repository.previous_quality(request.run_id,quality) if quality and quality.get('model_requested') else None
    gate=automatic_approval_quality(quality,getattr(request,'automatic_approval_limits',AutomaticApprovalLimits()),baseline)
    if not gate['ready']:
        approval={'status':'held','reason':'quality_threshold_exceeded','quality_gate':gate}
        await repository.record_application_standard(request.run_id,approval)
        return result.model_copy(update={'summary':{**result.summary,'automatic_application_standard':approval}})
    async with GoodsAuthoringClient() as api:
        readiness = await api.application_standard_readiness(request.run_id)
        if not readiness['ready']:
            approval = {'status':'held','reason':readiness['reason']}
        else:
            reference = next((a for a in result.artifacts if a.key.rsplit('/',1)[-1] == 'dictionary_standard.json'), None)
            if reference is None:
                reference = next((a for a in result.artifacts if a.key.rsplit('/',1)[-1] == 'dictionary_release.json'), None)
            if reference is None:
                approval = {'status':'held','reason':'dictionary_snapshot_not_available'}
            else:
                raw = await read_uri(reference.uri)
                if hashlib.sha256(raw).hexdigest() != reference.sha256:
                    raise ValueError('dictionary_snapshot_checksum_mismatch')
                used = approved_dictionary_snapshot(parse_dictionary_snapshot(raw))
                current = await api.dictionary_meaning('GET','/snapshot')
                if approved_dictionary_snapshot(current).checksum != used.checksum:
                    approval = {'status':'held','reason':'dictionary_changed_after_processing'}
                else:
                    release = await api.approve_application_standard({
                        'name':'자동 처리 기준 ' + request.run_id,
                        'source_run_id':request.run_id,
                        'expected_dictionary_checksum':current['checksum'],
                        'idempotency_key':str(uuid5(NAMESPACE_URL, 'teoria:automatic-standard:' + request.run_id)),
                        'rationale':'사용자가 활성화한 자동 승인 정책에 따라 원문 근거가 검증된 추출 기준을 고정한다. Business Ontology 게시나 사람의 의미 검토를 뜻하지 않는다.',
                    })
                    approval = {'status':'approved','approval_mode':'automatic_policy',
                        'release_id':str(release['release_id']),'approved_by':release['approved_by'],
                        'content_checksum':release['content_checksum']}
    approval['quality_gate']=gate
    await repository.record_application_standard(request.run_id, approval)
    return result.model_copy(update={'summary':{**result.summary,'automatic_application_standard':approval}})
