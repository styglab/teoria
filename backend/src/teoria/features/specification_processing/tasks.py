"""Prefect task boundaries for specification I/O, IE stages and canonical artifacts."""
from __future__ import annotations
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
from prefect import task
from prefect.cache_policies import NO_CACHE
from teoria.features.specification_processing.storage.artifact_store import artifact_store,read_uri
from teoria.integrations.codex import CodexRunner
from teoria.features.specification_processing.models import SpecificationRun,StandardArtifact
from teoria.features.specification_processing.extraction.extraction_validation import validate_checkpoint,isolate_extraction_failures

MAX_SOURCE_BYTES=25*1024*1024
TASK_OPTIONS={'persist_result':False,'cache_policy':NO_CACHE,'retries':0,'log_prints':False}

def run_key(request,leaf):return f'specification_processing/{request.run_id}/{leaf}'

async def load(path):return json.loads(await asyncio.to_thread(Path(path).read_text))
async def save(path,data):
    path=Path(path)
    await asyncio.to_thread(path.parent.mkdir,parents=True,exist_ok=True)
    await asyncio.to_thread(path.write_text,json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def runner(request):return CodexRunner(model=request.model,concurrency=request.model_concurrency,timeout=request.model_timeout_seconds)

async def each_document(workspace,request,operation):
    path=Path(workspace)/'work.json';items=await load(path);slots=asyncio.Semaphore(request.concurrency)
    async def one(entry):
        if entry.get('failure'):return
        async with slots:
            try:await operation(entry)
            except Exception as exc:
                from teoria.features.specification_processing.processing_errors import SpecificationProcessingError
                entry['failure']={'stage':operation.__name__,'reason':type(exc).__name__}
                if isinstance(exc,SpecificationProcessingError):
                    entry['failure'].update(code=exc.code,details=exc.details)
                await save(Path(workspace)/'processing'/entry['document_id']/'failure.json',entry['failure'])
    await asyncio.gather(*(one(e) for e in items))
    await save(path,items)


@task(name='00 규격서 원본 준비',**TASK_OPTIONS)
async def stage_original_documents(request:SpecificationRun,workspace:str):
    items=[];slots=asyncio.Semaphore(request.concurrency)
    async with artifact_store(request.artifact_root) as store:
        async def one(document):
            async with slots:
                leaf=f'sources/{document.document_id}{Path(document.filename).suffix.lower()}'
                try:data=await store.get(run_key(request,leaf))
                except FileNotFoundError:data=await read_uri(document.source_uri)
                digest=hashlib.sha256(data).hexdigest()
                if len(data)>MAX_SOURCE_BYTES:raise ValueError('source exceeds 25 MiB')
                if document.sha256 and digest!=document.sha256:raise ValueError('source checksum mismatch')
                local=Path(workspace)/leaf
                await asyncio.to_thread(local.parent.mkdir,parents=True,exist_ok=True)
                await asyncio.to_thread(local.write_bytes,data)
                artifact=await store.put(run_key(request,leaf),data,'application/octet-stream')
                return {'document_id':document.document_id,'notice_number':document.notice_number,
                    'source':{'path':leaf,'sha256':digest,'original_name':document.filename,'origin_uri':document.source_uri},
                    'artifact':artifact.model_dump(),'source_path':str(local)}
        results=await asyncio.gather(*(one(d) for d in request.documents),return_exceptions=True)
        for result in results:
            if isinstance(result,BaseException):raise result
        items=results
        # A failed run may already have its canonical extraction checkpoint uploaded.
        try:checkpoint=await store.get(run_key(request,'extracted.json'))
        except FileNotFoundError:checkpoint=None
        if checkpoint is None and request.extraction_checkpoint:
            checkpoint=await read_uri(request.extraction_checkpoint.uri)
            if hashlib.sha256(checkpoint).hexdigest()!=request.extraction_checkpoint.sha256:raise ValueError('checkpoint checksum mismatch')
        if checkpoint is not None:
            corpus=json.loads(checkpoint);validate_checkpoint(corpus,request,items)
            await save(Path(workspace)/'extracted.json',corpus)
    await save(Path(workspace)/'work.json',items)
    return checkpoint is not None

@task(name='01 문서 파싱·본문 역할 분류',**TASK_OPTIONS)
async def parse_documents(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.parsing.document_parser import parse_document,parser_runtime_identity
    from teoria.features.specification_processing.parsing.document_assessment import assess_document
    from teoria.features.specification_processing.storage.extraction_checkpoints import extraction_checkpoints
    model=runner(request)
    # OCR subprocesses compete for CPU; keep their budget independent of model I/O.
    parser_slots=asyncio.Semaphore(1)
    async with extraction_checkpoints(request) as checkpoints:
        runtime=await parser_runtime_identity(request.parser_python) if checkpoints.enabled else None
        async def parse_one(entry):
            folder=Path(workspace)/'processing'/entry['document_id'];await asyncio.to_thread(folder.mkdir,parents=True,exist_ok=True)
            inputs={'source_sha256':entry['source']['sha256'],'document_id':entry['document_id'],
                    'filename':entry['source']['original_name'],'parser_runtime':runtime}
            restored=await checkpoints.restore('parse',inputs,folder,entry['source_path'])
            if restored:
                context=await load(folder/'document.json');assessment=context['document_assessment']
                entry.setdefault('reused_stages',[]).append('parse')
            else:
                async with parser_slots:
                    context=await parse_document(Path(entry['source_path']),folder/'native.json',entry['document_id'],request.parser_python)
                assessment=await assess_document(context,model,folder)
                context['document_assessment']=assessment
                await save(folder/'document_assessment.json',assessment);await save(folder/'document.json',context)
                if assessment.get('status')=='classified':await checkpoints.record('parse',inputs,folder)
            if assessment['excluded']:
                entry['failure']={'stage':'document_assessment','reason':'not_specification','disposition':'excluded',
                                  'details':{'document_kind':assessment['document_kind']}}
        await each_document(workspace,request,parse_one)


@task(name='02 엔티티·계층·관계 추출',**TASK_OPTIONS)
async def extract_entity_relations(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import extract_entity_relations as extract
    from teoria.features.specification_processing.storage.extraction_checkpoints import extraction_checkpoints
    model=runner(request)
    async with extraction_checkpoints(request) as checkpoints:
        async def extract_one(entry):
            folder=Path(workspace)/'processing'/entry['document_id'];document=await load(folder/'document.json')
            inputs={'source_sha256':entry['source']['sha256'],'document':document}
            if await checkpoints.restore('composition',inputs,folder,entry['source_path']):
                entry.setdefault('reused_stages',[]).append('composition')
            else:
                await extract(document,folder/'inventory',model,checkpoints=checkpoints)
                await checkpoints.record('composition',inputs,folder)
        await each_document(workspace,request,extract_one)


@task(name='03 요구조건 추출·누락 구간 재추출',**TASK_OPTIONS)
async def extract_requirements(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.requirement_extraction import extract_requirements as extract
    from teoria.features.specification_processing.extraction.composition_review import assert_composition_preserved
    from teoria.features.specification_processing.storage.extraction_checkpoints import extraction_checkpoints
    model=runner(request)
    async with extraction_checkpoints(request) as checkpoints:
        async def extract_one(entry):
            folder=Path(workspace)/'processing'/entry['document_id'];out=folder/'attributes'
            document=await load(folder/'document.json');base=await load(folder/'inventory/graph.json')
            inputs={'source_sha256':entry['source']['sha256'],'document':document,'graph':base}
            restored=await checkpoints.restore('attributes',inputs,folder,entry['source_path'])
            if restored:
                entry.setdefault('reused_stages',[]).append('attributes')
                summary=await load(out/'summary.json');summary.update(new_model_calls=0,checkpoint_reused=True)
                await save(out/'summary.json',summary)
            else:
                await extract(entry['document_id'],folder/'inventory',out,model,None,False,
                              resolve_semantics=False,checkpoints=checkpoints)
            graph=await load(out/'attribute_graph.json');assert_composition_preserved(base,graph)
            summary=await load(out/'summary.json')
            if (not restored and not summary['failed_chunks'] and not summary.get('quarantined')
                    and not summary['uncovered_spec_fragments'] and not summary.get('target_recovery',{}).get('error_type')):
                await checkpoints.record('attributes',inputs,folder)
        await each_document(workspace,request,extract_one)


@task(name='04 대상·역할·범위 해석',**TASK_OPTIONS)
async def resolve_attribute_semantics(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics as resolve
    from teoria.features.specification_processing.extraction.composition_review import assert_composition_preserved
    from teoria.features.specification_processing.storage.extraction_checkpoints import extraction_checkpoints
    model=runner(request)
    async with extraction_checkpoints(request) as checkpoints:
        async def resolve_one(entry):
            folder=Path(workspace)/'processing'/entry['document_id'];out=folder/'attributes'
            document=await load(folder/'document.json');graph=await load(out/'attribute_graph.json')
            base=await load(folder/'inventory/graph.json')
            inputs={'source_sha256':entry['source']['sha256'],'document':document,'graph':graph}
            restored=await checkpoints.restore('semantics',inputs,folder,entry['source_path'])
            if restored:
                entry.setdefault('reused_stages',[]).append('semantics')
                graph=await load(out/'attribute_graph.json');summary=await load(out/'summary.json')
                semantic=summary['semantic_resolution']
                semantic.update(cached_batches=semantic['batches'],input_nodes=0,input_characters=0,
                                retried_attributes=0,recovered_attributes=0,model_failures=0,failed_batches=0)
                summary.update(new_model_calls=0,checkpoint_reused=True)
            else:
                summary=await load(out/'summary.json')
                semantic=await resolve(document,graph,graph['attributes'],model,out,checkpoints=checkpoints)
                from teoria.features.specification_processing.extraction.table_attribute_context import recover_table_attribute_context
                semantic['table_context']=recover_table_attribute_context(document,graph,graph['attributes'])
                from teoria.features.specification_processing.extraction.inline_attribute_units import recover_inline_attribute_units
                semantic['inline_units']=recover_inline_attribute_units(document,graph['attributes'])
                summary['semantic_resolution']=semantic
            assert_composition_preserved(base,graph)
            summary['other_requirement_clauses']=sum(r.get('category')=='other' for r in graph.get('requirements',[]) if r.get('observation_type')=='source_clause')
            summary['attributes']=len(graph['attributes'])
            summary['numeric_comparisons']=sum(a['normalized']['comparison_rule']=='numeric_requirement' for a in graph['attributes'])
            summary['unresolved_units']=sum(a['normalized']['unit_status']=='unmapped' for a in graph['attributes'])
            if semantic['unresolved'] or semantic.get('unresolved_scope',0):summary['status']='partial'
            await save(out/'attribute_graph.json',graph);await save(out/'summary.json',summary)
            if not restored and not semantic['failed_batches']:await checkpoints.record('semantics',inputs,folder)
        await each_document(workspace,request,resolve_one)

@task(name='05 추출 결과 검증·저장',**TASK_OPTIONS)
async def persist_extraction(request:SpecificationRun,workspace:str,reused:bool):
    from teoria.features.specification_processing.extraction.extraction_status import document_extraction_status,held_relation_counts
    items=await load(Path(workspace)/'work.json')
    if reused:
        corpus=await load(Path(workspace)/'extracted.json')
        for d in corpus['documents']+corpus['unavailable_documents']:
            source=next(e for e in items if e['document_id']==d['document_id'])
            d['source']=source['source'];d['notice_number']=source['notice_number']
    else:
        documents=[];failed=[]
        for entry in items:
            common={k:entry[k] for k in ['document_id','notice_number','source']}
            if entry.get('failure'):
                failed.append({**common,**entry['failure']});continue
            folder=Path(workspace)/'processing'/entry['document_id'];out=folder/'attributes'
            graph=await load(out/'attribute_graph.json');context=await load(folder/'document.json');summary=await load(out/'summary.json')
            for key in ['source_path','parse_path','source_file_reverified']:context.pop(key,None)
            attributes=[]
            for a in graph['attributes']:
                # Only parser evidence and accepted observations survive; no raw model output.
                row={k:v for k,v in a.items() if k not in {'normalized','ontology_property_id','wire_format_projection'}}
                row['evidence']={k:v for k,v in a['evidence'].items() if k!='quote'};attributes.append(row)
            documents.append({**common,'classification_code':request.classification_code,'parsed_document':context,
                'parser':{'name':'kory_parser','version':context['parser_version'],
                          'ocr':context.get('ocr',False),'ocr_enabled':context.get('ocr_enabled',False),
                          'ocr_pages':context.get('ocr_pages',[]),
                          'unreadable_ocr_pages':context.get('unreadable_ocr_pages',[])},
                'entities':graph['entities'],'relations':graph['relations'],'held_relations':graph.get('held_relations',[]),'inventory_ids':graph.get('inventory_ids',[]),
                **({'composition_inventory':graph['composition_inventory']} if 'composition_inventory' in graph else {}),
                'inventory_assessment':graph.get('inventory_assessment',{}),
                'declared_quantities':graph.get('declared_quantities',[]),'attributes':attributes,
                'requirements':graph.get('requirements',[]),
                'extraction_status':document_extraction_status(summary,graph,context),
                'attribute_input_coverage':summary['input_coverage'],
                'unresolved_extraction':{**{k:summary[k] for k in ['failed_chunks','uncovered_spec_fragments','semantic_resolution','recovery_passes']},
                                         'reused_stages':entry.get('reused_stages',[]),
                                         'held_relations':len(graph.get('held_relations',[])),
                                         'coverage_by_kind':summary.get('coverage_by_kind',{}),
                                         'coverage_reasons':summary.get('coverage_reasons',{}),
                                         'repeated_target_mentions':summary.get('repeated_target_mentions',0),
                                         'specification_references':summary.get('specification_references',0),
                                         'other_requirement_clauses':summary.get('other_requirement_clauses',0),
                                         'target_recovery':summary.get('target_recovery',{}),
                                         **held_relation_counts(graph)}})
        corpus={'schema_version':'specification_extraction_v1','classification_code':request.classification_code,'documents':documents,'unavailable_documents':failed,
            'extraction_policy':'product_specifications_with_bounded_recovery_and_other_source_clauses'}
    if not reused:
        corpus=isolate_extraction_failures(corpus,request,items)
    from teoria.features.specification_processing.extraction.composition_hierarchy import composition_hierarchy
    for document in corpus['documents']:
        document['composition_hierarchy']=composition_hierarchy(document)
    validate_checkpoint(corpus,request,items)
    await save(Path(workspace)/'extracted.json',corpus)
    async with artifact_store(request.artifact_root) as store:
        return (await store.put(run_key(request,'extracted.json'),await asyncio.to_thread((Path(workspace)/'extracted.json').read_bytes))).model_dump()

@task(name='06 표준 사전 관리·연결',**TASK_OPTIONS)
async def resolve_dictionary(request:SpecificationRun,workspace:str,extraction_ref:dict):
    if not request.use_expression_dictionary:
        return None
    from teoria.features.specification_processing.normalization.dictionary_alignment import align_dictionary
    corpus=await load(Path(workspace)/'extracted.json')
    maintenance=None
    if request.mode=='standard_management' and corpus['documents']:
        from teoria.features.specification_processing.normalization.dictionary_incremental import update_standard_dictionary
        maintenance=await update_standard_dictionary(request,corpus,extraction_ref)
    return await align_dictionary(request,corpus,extraction_ref,maintenance=maintenance)


def attach_source_term_alignment(normalized,dictionary):
    if dictionary is not None:
        normalized['dictionary_meanings']=dictionary.get('meaning_alignment',{})
        normalized['source_term_alignment']={'artifact':dictionary['alignment_ref'],
            'operation_id':dictionary['result']['operation_id'],'summary':dictionary['summary'],
            'semantic_maturity':'source_literal','human_review_performed':False,
            'meaning_summary':dictionary.get('meaning_summary',{})}


@task(name='06b 게시 Ontology 참고·의미 연결 비교', **TASK_OPTIONS)
async def align_with_ontology(request:SpecificationRun,workspace:str,extraction_ref:dict,dictionary):
    from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
    from teoria.features.specification_processing.normalization.ontology_context import load_published_context
    from teoria.features.specification_processing.normalization.ontology_alignment import propose_links
    corpus=await load(Path(workspace)/'extracted.json')
    async with GoodsAuthoringClient() as api:
        snapshot,catalog=await load_published_context(request.ontology_alignment,api,standard=request.standard)
    report=await propose_links(corpus,snapshot,catalog,(dictionary or {}).get('meaning_alignment'),runner(request),
                               Path(workspace)/'ontology_alignment_inference')
    context_input = request.ontology_alignment
    report.update(extraction_ref=extraction_ref, context_input_ref=(
        context_input.snapshot.model_dump(mode='json') if context_input.snapshot is not None
        else {'publications': [ref.model_dump(mode='json') for ref in context_input.publications]}))
    async with artifact_store(request.artifact_root) as store:
        context_ref=await store.put(run_key(request,'ontology_context.json'),snapshot.model_dump_json().encode())
        report['context_artifact']=context_ref.model_dump(mode='json')
        report_ref=await store.put(run_key(request,'ontology_alignment.json'),
                                   (json.dumps(report,ensure_ascii=False,sort_keys=True)+'\n').encode())
        candidates={'schema_version':1,'artifact_kind':'specification_ontology_context_review_candidates',
            'authority':'suggestion','auto_approve':False,'reason':'selected_context_or_ontology_gap',
            'extraction_ref':extraction_ref,'context_artifact':context_ref.model_dump(mode='json'),
            'observations':[row for row in report['observations'] if row['ontology_review_candidate']]}
        unresolved_ref=await store.put(run_key(request,'ontology_alignment_unresolved.json'),
                                       (json.dumps(candidates,ensure_ascii=False,sort_keys=True)+'\n').encode())
    return {'report':report,'artifacts':[context_ref.model_dump(mode='json'),report_ref.model_dump(mode='json'),
                                        unresolved_ref.model_dump(mode='json')]}


@task(name='07 표준 의미 적용',**TASK_OPTIONS)
async def select_and_map_standard(request:SpecificationRun,workspace:str,extraction_ref:dict|None=None,dictionary=None,*,ontology_alignment=None):
    from teoria.features.specification_processing.normalization.standard_versioning import manage_standard
    from teoria.features.specification_processing.normalization.standard_application import map_standard
    from teoria.features.specification_processing.models import StandardReference
    corpus=await load(Path(workspace)/'extracted.json');standard=None
    if request.standard:
        raw=await read_uri(request.standard.uri)
        if hashlib.sha256(raw).hexdigest()!=request.standard.sha256:raise ValueError('standard checksum mismatch')
        payload=json.loads(raw)
        if payload.get('artifact_kind')=='goods_normalization_package':
            from teoria.features.goods_normalization.contracts import NormalizationPackage
            from teoria.features.specification_processing.normalization.profile_application import apply_profile
            package=NormalizationPackage.model_validate(payload)
            meaning_alignment = dictionary.get('meaning_alignment') if dictionary else None
            if not request.use_expression_dictionary:
                # Disabling registration must not turn unreviewed aliases into approved meaning.
                meaning_alignment = {'policy_version':'published_ontology_expression_v2', 'documents':[]}
            normalized,candidates=apply_profile(corpus,package,run_id=request.run_id,
                meaning_alignment=meaning_alignment)
            normalized['standard_ref']=request.standard.model_dump()
            normalized['extraction_ref']=extraction_ref
            attach_source_term_alignment(normalized,dictionary)
            if ontology_alignment is not None:
                normalized['ontology_alignment']=ontology_alignment['report']
            candidates['extraction_ref']=extraction_ref
            artifacts=[]
            async with artifact_store(request.artifact_root) as store:
                await save(Path(workspace)/'normalized.json',normalized)
                artifacts.append((await store.put(run_key(request,'normalized.json'),await asyncio.to_thread((Path(workspace)/'normalized.json').read_bytes))).model_dump())
                if request.mode=='standard_management':
                    await save(Path(workspace)/'meaning_candidates.json',candidates)
                    artifacts.append((await store.put(run_key(request,'meaning_candidates.json'),(json.dumps(candidates,ensure_ascii=False,indent=2)+'\n').encode())).model_dump())
            return {'artifacts':artifacts,'standard':request.standard.model_dump()}
        standard=StandardArtifact.model_validate(payload)
    candidates=None
    if request.mode=='standard_management':standard,candidates,normalized=manage_standard(
        corpus,standard,request.standard.sha256 if request.standard else None,
        auto_apply_source_literals=request.auto_apply_source_literals)
    else:normalized=map_standard(corpus,standard)
    artifacts=[]
    async with artifact_store(request.artifact_root) as store:
        if request.mode=='standard_management':
            data=(standard.model_dump_json(indent=2)+'\n').encode()
            ref=await store.put(f'specification_processing/standards/{standard.version}/standard.json',data)
            standard_ref=StandardReference(uri=ref.uri,sha256=ref.sha256);artifacts.append(ref.model_dump())
            ref=await store.put(run_key(request,'meaning_candidates.json'),(json.dumps(candidates,ensure_ascii=False,indent=2)+'\n').encode());artifacts.append(ref.model_dump())
        else:standard_ref=request.standard
        await save(Path(workspace)/'standard_definitions.json', [d.model_dump() if hasattr(d, 'model_dump') else d for d in standard.definitions])
        normalized['standard_ref']=standard_ref.model_dump()
        attach_source_term_alignment(normalized,dictionary)
        if ontology_alignment is not None:
            normalized['ontology_alignment']=ontology_alignment['report']
        await save(Path(workspace)/'normalized.json',normalized)
        ref=await store.put(run_key(request,'normalized.json'),await asyncio.to_thread((Path(workspace)/'normalized.json').read_bytes));artifacts.append(ref.model_dump())
    if candidates is not None:await save(Path(workspace)/'meaning_candidates.json',candidates)
    return {'artifacts':artifacts,'standard':standard_ref.model_dump()}

@task(name='08 결과 보고서 저장',**TASK_OPTIONS)
async def persist_report(request:SpecificationRun,workspace:str,standard_version:str):
    from teoria.features.specification_processing.reporting import render_report
    corpus=await load(Path(workspace)/'extracted.json');normalized=await load(Path(workspace)/'normalized.json')
    candidates=await load(Path(workspace)/'meaning_candidates.json') if request.mode=='standard_management' else None
    text=render_report(corpus,normalized,standard_version,candidates)
    async with artifact_store(request.artifact_root) as store:
        return (await store.put(run_key(request,'index.md'),text.encode(),'text/markdown')).model_dump()


@task(name='09 문서별 탐색 결과 저장', **TASK_OPTIONS)
async def persist_document_results(request: SpecificationRun, workspace: str):
    from teoria.features.specification_processing.catalog.results import store_document_results
    corpus = await load(Path(workspace) / 'extracted.json')
    normalized = await load(Path(workspace) / 'normalized.json')
    async with artifact_store(request.artifact_root) as store:
        definitions = await load(Path(workspace)/'standard_definitions.json') if (Path(workspace)/'standard_definitions.json').exists() else []
        return await store_document_results(store, request.run_id, corpus, normalized, definitions=definitions)


@task(name='10 처리 버전·출처 기록 저장', **TASK_OPTIONS)
async def persist_execution_receipt(request: SpecificationRun, workspace: str, revision: str, references: list):
    corpus = await load(Path(workspace) / 'extracted.json')
    normalized = await load(Path(workspace) / 'normalized.json')
    source_hashes = {d['document_id']: d['source']['sha256']
                     for d in [*corpus['documents'], *corpus['unavailable_documents']]}
    receipt = {
        'schema_version': 1, 'run_id': request.run_id, 'mode': request.mode,
        'input_fingerprint': request.input_fingerprint(), 'processor_revision': revision,
        'model': {'requested': request.model, 'immutable_identity_verified': False},
        'parser_versions': sorted({d['parser']['version'] for d in corpus['documents']}),
        'sources': [{'document_id': d.document_id, 'sha256': source_hashes[d.document_id]} for d in request.documents],
        'application_release_id': str(request.application_release_id) if request.application_release_id else None,
        'standard': request.standard.model_dump(mode='json') if request.standard else None,
        'dictionary': request.dictionary_standard.model_dump(mode='json') if request.dictionary_standard else None,
        'ontology': normalized.get('ontology'),
        'ontology_alignment': request.ontology_alignment.model_dump(mode='json') if request.ontology_alignment else None,
        'artifacts': [{'key': a['key'], 'uri': a['uri'], 'sha256': a['sha256']} for a in references],
        'quality_evaluation': 'not_attached',
    }
    async with artifact_store(request.artifact_root) as store:
        return (await store.put(run_key(request, 'execution_receipt.json'),
            (json.dumps(receipt, ensure_ascii=False, sort_keys=True) + '\n').encode())).model_dump()
