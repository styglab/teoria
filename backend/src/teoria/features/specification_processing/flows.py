"""Operational specification flows: ordered tasks, immutable artifacts, final DB checkpoint."""
import asyncio
from pathlib import Path
import hashlib
from prefect import flow,task
from prefect.cache_policies import NO_CACHE
from teoria.features.specification_processing.models import ArtifactRef,RunResult,SpecificationRun,StandardReference
from teoria.features.specification_processing.storage.run_repository import SpecificationRepository
from teoria.features.specification_processing import tasks
from teoria.features.specification_processing.storage.processing_workspace import processing_workspace
from teoria.features.specification_processing.management_parameters import (
    StandardManagementParameters, DocumentSelection, DictionaryManagement, ManagementExecution,
)


def processor_revision():
    import teoria.features.goods_normalization.contracts
    import teoria.integrations.codex
    import inspect
    from teoria.features.semantic_modeling.goods_dictionary.contracts import source_literal_definition
    import teoria.features.semantic_modeling.goods_dictionary.meaning_contracts as meaning_contracts
    root=Path(__file__).resolve().parent
    paths=sorted(p for p in root.rglob('*.py') if not p.name.startswith('evaluation'))
    contract_root=Path(teoria.features.goods_normalization.contracts.__file__).parent
    contract_paths=sorted(contract_root.rglob('*.py'))
    body=b''.join(p.relative_to(root).as_posix().encode()+p.read_bytes() for p in paths)
    body+=b''.join(b'goods_normalization/'+p.relative_to(contract_root).as_posix().encode()+p.read_bytes() for p in contract_paths)
    body+=b'goods_dictionary_contract/'+Path(inspect.getfile(source_literal_definition)).read_bytes()
    body+=b'goods_dictionary_meaning_contract/'+Path(inspect.getfile(meaning_contracts)).read_bytes()
    runner_root=Path(teoria.integrations.codex.__file__).parent
    body+=b''.join(b'codex_inference/'+p.relative_to(runner_root).as_posix().encode()+p.read_bytes() for p in sorted(runner_root.rglob('*.py')))
    return hashlib.sha256(body).hexdigest()

@task(name='규격 처리 실행 시작',persist_result=False,cache_policy=NO_CACHE)
async def start_execution(request:SpecificationRun):
    fingerprint=hashlib.sha256((request.input_fingerprint()+processor_revision()).encode()).hexdigest()
    return await SpecificationRepository.from_environment().start(request,fingerprint)

@task(name='규격 처리 완료 체크포인트',persist_result=False,cache_policy=NO_CACHE)
async def complete_execution(result:RunResult):
    await SpecificationRepository.from_environment().complete(result)

@task(name='규격 처리 실패 기록',persist_result=False,cache_policy=NO_CACHE)
async def fail_execution(run_id,error_code):
    await SpecificationRepository.from_environment().fail(run_id,error_code)

async def extract_documents(request:SpecificationRun,workspace:str):
    """Shared production/evaluation Task sequence; no DB lifecycle or standard selection."""
    reused=await tasks.stage_original_documents(request,workspace)
    if not reused:
        await tasks.parse_documents(request,workspace)
        await tasks.extract_entity_relations(request,workspace)
        await tasks.extract_requirements(request,workspace)
        await tasks.resolve_attribute_semantics(request,workspace)
    ref=await tasks.persist_extraction(request,workspace,reused)
    return ref,reused


@flow(name='procurement-extraction-evaluation',persist_result=False,log_prints=False)
async def extraction_evaluation_flow(manifest:dict,workspace:str):
    request=SpecificationRun.model_validate(manifest)
    if request.extraction_checkpoint is not None:
        raise ValueError('IE evaluation must rerun extraction, not reuse a checkpoint')
    ref,_=await extract_documents(request,workspace)
    return ref

async def execute_specification_run(request:SpecificationRun, *, extra_artifacts=(), extra_summary=None):
    replay=await start_execution(request)
    if replay is not None:return replay
    try:
        async with processing_workspace(request.artifact_root,request.run_id,'processing') as working:
            temporary=str(working.path)
            # Clients, parser output and model responses never outlive this workspace.
            extracted_ref,reused=await extract_documents(request,temporary)      # 01–05
            dictionary=await tasks.resolve_dictionary(request,temporary,extracted_ref)        # 06
            selection=await tasks.select_and_map_standard(request,temporary,extracted_ref,dictionary) # 07
            normalized=await tasks.load(Path(temporary)/'normalized.json')
            report_ref=await tasks.persist_report(request,temporary,normalized['standard_version']) # 08
            document_refs=await tasks.persist_document_results(request,temporary) # 09
            corpus=await tasks.load(Path(temporary)/'extracted.json');work=await tasks.load(Path(temporary)/'work.json')
            document_results=[]
            for d in corpus['documents']:
                state='partial' if d.get('extraction_status')=='partial' else 'extracted'
                document_results.append({'document_id':d['document_id'],'notice_number':d.get('notice_number'),
                    'status':state,'source_sha256':d['source']['sha256'],
                    'result_summary':{'entities':len(d['entities']),'relations':len(d['relations']),'attributes':len(d['attributes']),
                        'quality':d.get('unresolved_extraction',{}),'parser_version':d['parser']['version'],
                        'dictionary_contexts':[{k:v for k,v in stamp.items() if k!='document_id'}
                            for stamp in dictionary.get('context_stamps',[]) if stamp['document_id']==d['document_id']]}})
            for d in corpus['unavailable_documents']:
                document_results.append({'document_id':d['document_id'],'notice_number':d.get('notice_number'),
                    'status':'excluded' if d.get('disposition')=='excluded' else 'failed','source_sha256':d['source']['sha256'],
                    'result_summary':{k:d[k] for k in ('stage','reason','code','details','disposition') if k in d}})
            partial=any(d.get('disposition')!='excluded' for d in corpus['unavailable_documents']) or any(d['status']=='partial' for d in document_results) or any(
                normalized.get(key,{}).get('automatically_deferred',0)>0 for key in ['summary','entity_summary','relation_summary'])
            partial=partial or dictionary['summary'].get('held',0)>0 or dictionary['summary'].get('proposed',0)>0
            semantic_summary=dictionary['summary'].get('semantic_authoring',{})
            partial=partial or semantic_summary.get('held',0)>0 or semantic_summary.get('proposed',0)>0
            partial=partial or dictionary.get('meaning_summary',{}).get('held',0)>0
            all_excluded=bool(corpus['unavailable_documents']) and all(d.get('disposition')=='excluded' for d in corpus['unavailable_documents'])
            state='completed' if all_excluded else 'failed' if not corpus['documents'] else 'partial' if partial else 'completed'
            diagnostics=await working.publish()
            result=RunResult(run_id=request.run_id,status=state,
                artifacts=sorted([ArtifactRef.model_validate(a) for a in [*extra_artifacts,*document_refs,*diagnostics,*(e['artifact'] for e in work),extracted_ref,*dictionary['artifacts'],*selection['artifacts'],report_ref]],key=lambda a:a.key),
                document_results=sorted(document_results,key=lambda d:d['document_id']),standard=StandardReference.model_validate(selection['standard']),
                summary={'documents':len(corpus['documents']),'failed_documents':sum(d.get('disposition')!='excluded' for d in corpus['unavailable_documents']),
                    'excluded_documents':sum(d.get('disposition')=='excluded' for d in corpus['unavailable_documents']),
                    'attributes':sum(len(d['attributes']) for d in corpus['documents']),**normalized['summary'],
                    'entity_normalization':normalized.get('entity_summary',{}),'relation_normalization':normalized.get('relation_summary',{}),
                    'human_approval_required':False,'reused_extraction':reused,
                    'dictionary':dictionary['summary'],'dictionary_operation_id':dictionary['result']['operation_id'],**(extra_summary or {})})
            # This is the only success/partial checkpoint: every referenced object exists first.
            await complete_execution(result)
            return result
    except BaseException as exc:
        try:await asyncio.shield(fail_execution(request.run_id,type(exc).__name__))
        except Exception:pass  # Preserve the processing error; no credentials or raw response are logged.
        raise

@flow(name='procurement-standard-management',persist_result=False,log_prints=False)
async def standard_management_flow(
    manifest:dict|None=None,
    classification_code:str|None=None,
    target_specifications:int=30,
    selection:DocumentSelection=DocumentSelection(),
    management:DictionaryManagement=DictionaryManagement(),
    execution:ManagementExecution=ManagementExecution(),
):
    if manifest is not None and (classification_code is not None or target_specifications!=30 or
        selection!=DocumentSelection() or management!=DictionaryManagement() or execution!=ManagementExecution()):
        raise ValueError('use either manifest or the individual parameters, not both')
    if manifest is not None and 'mode' in manifest:
        request=SpecificationRun.model_validate(manifest)
        if request.mode!='standard_management':raise ValueError('mode must be standard_management')
        return await execute_specification_run(request)
    from teoria.features.specification_processing.management_batch import execute_management_batch
    parameters=StandardManagementParameters.model_validate(manifest if manifest is not None else {
        'classification_code':classification_code,'target_specifications':target_specifications,
        'selection':selection,'management':management,'execution':execution})
    return await execute_management_batch(parameters)

@flow(name='procurement-document-processing',persist_result=False,log_prints=False)
async def document_processing_flow(manifest:dict):
    request=SpecificationRun.model_validate(manifest)
    if request.mode!='document_processing':raise ValueError('mode must be document_processing')
    return await execute_specification_run(request)
