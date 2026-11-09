"""Assembly of selected-document extraction, held-out checks and the existing 00–08 path."""
import hashlib
import json
from pathlib import Path
from prefect import task
from prefect.cache_policies import NO_CACHE
from teoria.features.specification_processing.models import SourceDocument, SpecificationRun, StandardArtifact
from teoria.features.specification_processing.storage.artifact_store import artifact_store, read_uri
from teoria.features.specification_processing.document_selection import select_specifications
from teoria.features.specification_processing.storage.processing_workspace import processing_workspace
from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import approved_dictionary_snapshot, parse_dictionary_snapshot


@task(name='기준 사전 확인', persist_result=False, cache_policy=NO_CACHE)
async def check_baseline(parameters):
    ref=parameters.management.baseline_dictionary
    pinned=None
    if ref:
        raw=await read_uri(ref.uri)
        if hashlib.sha256(raw).hexdigest()!=ref.sha256:raise ValueError('baseline dictionary checksum mismatch')
        pinned=approved_dictionary_snapshot(parse_dictionary_snapshot(raw))
    if parameters.management.purpose=='quality_evaluation':return pinned
    async with GoodsAuthoringClient() as api:
        current=approved_dictionary_snapshot(await api.dictionary_meaning('GET','/snapshot'))
    if pinned is not None and pinned.checksum!=current.checksum:
        raise ValueError('baseline dictionary is no longer current; select the current release')
    return current


def split_documents(documents,holdout_count,minimum_development):
    """Never put attachments from the same notice in both development and evaluation."""
    # A copied original can appear in different notices; group both identities transitively.
    parents=list(range(len(documents)))
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    seen={}
    for index,document in enumerate(documents):
        keys=[('hash',document['source']['sha256'])]
        if document.get('notice_number'):keys.append(('notice',document['notice_number']))
        for key in keys:
            if key in seen:parents[root(index)]=root(seen[key])
            else:seen[key]=index
    groups={}
    for index,document in enumerate(documents):
        groups.setdefault(root(index),[]).append(document['document_id'])
    if len(groups)<2:return [],[d['document_id'] for d in documents]
    validation=[]
    for group in reversed(list(groups.values())):
        if len(documents)-len(validation)-len(group)<minimum_development:continue
        validation.extend(group)
        if len(validation)>=holdout_count:break
    if len(validation)<holdout_count:return [],[d['document_id'] for d in documents]
    excluded=set(validation)
    return validation,[d['document_id'] for d in documents if d['document_id'] not in excluded]


@task(name='사전 구축·평가 문서 분리', persist_result=False, cache_policy=NO_CACHE)
async def prepare_batch(parameters,selection,*,baseline=None):
    from teoria.features.specification_processing.flows import extract_documents
    from teoria.features.specification_processing import tasks
    settings=parameters.execution
    documents=[SourceDocument.model_validate({k:v for k,v in row.items() if k in SourceDocument.model_fields}) for row in selection['selected']]
    if not documents:return {'status':'held','reason':'no_specification_files','selection':selection}
    baseline=baseline if baseline is not None else await check_baseline(parameters)
    prefix='specification_processing/'+selection['run_id']+'/'
    async with artifact_store(selection['artifact_root']) as store:
        baseline_artifact=await store.put(prefix+'baseline_dictionary.json',
            (baseline.model_dump_json(indent=2)+'\n').encode())
    baseline_ref={'uri':baseline_artifact.uri,'sha256':baseline_artifact.sha256}
    request=SpecificationRun(run_id=selection['run_id'],mode='standard_management',
        classification_code=parameters.classification_code,documents=documents,artifact_root=selection['artifact_root'],
        dictionary_meaning_auto_approve=False,**settings.model_dump(exclude={'run_id','artifact_root'}))
    if request.ontology_alignment is not None:
        from teoria.features.specification_processing.normalization.ontology_context import load_published_context
        async with GoodsAuthoringClient() as api:
            await load_published_context(request.ontology_alignment,api)
    async with processing_workspace(request.artifact_root,request.run_id,'extraction') as working:
        workspace=str(working.path)
        extracted_ref,_=await extract_documents(request,workspace)
        corpus=await tasks.load(Path(workspace)/'extracted.json')
        diagnostics=await working.publish()
    complete=[d for d in corpus['documents'] if d.get('extraction_status')!='partial']
    is_evaluation=parameters.management.purpose=='quality_evaluation'
    validation,development=split_documents(complete,parameters.management.holdout_documents,
        parameters.management.minimum_development_documents)
    if is_evaluation:
        development=[d['document_id'] for d in corpus['documents']];validation=[]
    else:
        # Partial extractions can be inspected, but cannot satisfy the quality gate.
        if not development:
            development=[d['document_id'] for d in corpus['documents'] if d.get('extraction_status')=='partial']
    if not development:return {'status':'held','reason':'no_specification_content' if corpus['unavailable_documents'] and all(d.get('disposition')=='excluded' for d in corpus['unavailable_documents']) else 'no_parseable_specifications','selection':selection}
    gate=not is_evaluation and len(validation)>=parameters.management.holdout_documents and (
        len([d for d in complete if d['document_id'] in development])>=parameters.management.minimum_development_documents)
    async with artifact_store(request.artifact_root) as store:
        refs=[baseline_artifact.model_dump(mode='json'),extracted_ref,*diagnostics,*[d['artifact'] for d in selection['selected']]]
        async def save(name,body):
            ref=await store.put(prefix+name,(json.dumps(body,ensure_ascii=False,indent=2)+'\n').encode())
            refs.append(ref.model_dump(mode='json'));return {'uri':ref.uri,'sha256':ref.sha256}
        def subset(ids):
            return {**corpus,'documents':[d for d in corpus['documents'] if d['document_id'] in ids], 'unavailable_documents':[]}
        training=await save('development_checkpoint.json',subset(set(development)))
        # Historical evidence is distinct from training and cannot contain held-out documents.
        validation_notices={d.get('notice_number') for d in corpus['documents'] if d['document_id'] in validation}-{None}
        evidence_ids={d['document_id'] for d in corpus['documents'] if d['document_id'] not in validation
                      and (not d.get('notice_number') or d['notice_number'] not in validation_notices)}
        evidence=await save('evidence_checkpoint.json',subset(evidence_ids))
        validation_ref=await save('validation_checkpoint.json',subset(set(validation))) if validation else None
        # The run-level canonical extraction must contain the exact development set.
        # Full extraction lives in the preparation run; execution uses a distinct stable ID.
        updates={'run_id':request.run_id+'_apply','documents':[d for d in documents if d.document_id in development],
            'auto_apply_source_literals':parameters.management.auto_apply and not is_evaluation,
            'auto_approve_application_standard':parameters.management.auto_apply and not is_evaluation,
            'dictionary_auto_approve':parameters.management.auto_apply and not is_evaluation,
            'extraction_checkpoint':training,'dictionary_meaning_auto_approve':parameters.management.auto_apply and gate and baseline.schema_version == 1,
            'dictionary_reconcile':parameters.management.force_review and not is_evaluation,
            'dictionary_validation_corpus':[validation_ref] if validation_ref else [],
            'dictionary_evidence_corpus':[] if is_evaluation else [evidence],
            'dictionary_baseline':baseline_ref,
            'dictionary_require_validation':not is_evaluation,
            'dictionary_max_held_source_ids':parameters.management.max_held_source_ids}
        if is_evaluation:
            standard=StandardArtifact(version='dictionary_evaluation',definitions=[],bindings=[],classification_code=parameters.classification_code)
            standard_ref=await save('evaluation_standard.json',standard.model_dump(mode='json'))
            updates.update(mode='document_processing',standard=standard_ref,
                dictionary_standard=baseline_ref,dictionary_baseline=None,
                dictionary_reconcile=False,dictionary_require_validation=False,dictionary_auto_approve=False)
        summary={'status':'ready','purpose':parameters.management.purpose,'force_review':parameters.management.force_review,
            'target':parameters.target_specifications,
            'acquired':len(documents),'parsed':len(corpus['documents']),'unavailable':sum(d.get('disposition')!='excluded' for d in corpus['unavailable_documents']),
            'excluded':sum(d.get('disposition')=='excluded' for d in corpus['unavailable_documents']),
            'usable_complete_documents':len(complete),'usable_shortfall':max(0,parameters.target_specifications-len(complete)),
            'partial_extractions':len(corpus['documents'])-len(complete),'development_documents':development,
            'validation_documents':validation,'automatic_application_enabled':updates['dictionary_meaning_auto_approve'],
            'quality_gate':'read_only_evaluation' if is_evaluation else
                'ontology_review_required' if baseline.schema_version == 2 else
                'separate_documents_and_no_semantic_regression' if gate else 'insufficient_independent_documents',
            'requested_auto_apply':parameters.management.auto_apply,
            'baseline_dictionary':baseline_ref,'baseline_dictionary_checksum':baseline.checksum}
        await save('management_batch.json',summary)
        selected_ref=await store.get(prefix+'document_selection.json')
        # Include selection in the final Data DB artifact references as well as preparation files.
        from teoria.features.specification_processing.models import ArtifactRef
        refs.append(ArtifactRef(key=prefix+'document_selection.json',uri=request.artifact_root.rstrip('/')+'/'+prefix+'document_selection.json',
            sha256=hashlib.sha256(selected_ref).hexdigest(),size_bytes=len(selected_ref)).model_dump(mode='json'))
        execution=SpecificationRun.model_validate({**request.model_dump(mode='json'),**updates})
        return {'status':'ready','request':execution.model_dump(mode='json'),'artifacts':refs,'summary':summary,'selection':selection}


async def execute_management_batch(parameters):
    from teoria.features.specification_processing.flows import execute_specification_run
    baseline=await check_baseline(parameters)
    selection=await select_specifications(parameters)
    prepared=await prepare_batch(parameters,selection,baseline=baseline)
    if prepared['status']!='ready':return prepared
    return await execute_specification_run(SpecificationRun.model_validate(prepared['request']),
        extra_artifacts=prepared['artifacts'],extra_summary={'management_batch':prepared['summary']})
