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
from teoria.features.specification_processing.parsing.document_evidence import source_quote,literal

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


def validate_checkpoint(corpus,request,source_items):
    if corpus.get('classification_code')!=request.classification_code:raise ValueError('checkpoint classification mismatch')
    expected={e['document_id']:e['source']['sha256'] for e in source_items}
    actual=corpus['documents']+corpus['unavailable_documents']
    if len(actual)!=len(expected) or {d['document_id'] for d in actual}!=set(expected):raise ValueError('checkpoint document set mismatch')
    for d in actual:
        if d['source']['sha256']!=expected[d['document_id']]:raise ValueError('checkpoint source mismatch')
    for d in corpus['documents']:
        ids={e['id'] for e in d['entities']};nodes={n['node_id'] for n in d['parsed_document']['nodes']}
        if len(ids)!=len(d['entities']):raise ValueError('duplicate entity ID')
        if any(r['source_id'] not in ids or r['target_id'] not in ids for r in d['relations']):raise ValueError('invalid relation')
        from teoria.features.specification_processing.extraction.entity_relation_extraction import relation_type_errors
        kinds={e['id']:e.get('kind') for e in d['entities']}
        for relation in d['relations']:
            errors=relation_type_errors(relation['kind'],kinds[relation['source_id']],kinds[relation['target_id']])
            if errors:raise ValueError('invalid relation type: '+'; '.join(errors))
        from teoria.features.specification_processing.extraction.requirement_clauses import validate_legacy_obligation
        for requirement in d.get('requirements',[]):
            if requirement.get('observation_type')=='obligation':
                validate_legacy_obligation(requirement,ids,d['parsed_document'])
        from teoria.features.specification_processing.extraction.target_names import validate_materialized_names
        for entity in d['entities']:
            validate_materialized_names(entity,d['parsed_document'])
        attribute_ids=set()
        for a in d['attributes']:
            if a['id'] in attribute_ids or not set(a['subject_ids'])<=ids:raise ValueError('invalid attribute ID or subject')
            attribute_ids.add(a['id']);quote=literal(source_quote(d,a))
            for key in ['value_raw','unit_raw','operator_raw']:
                if a.get(key) and literal(a[key]) not in quote:raise ValueError('source literal mismatch')
            if any(literal(q) not in quote for q in a.get('qualifiers_raw',[])):raise ValueError('source qualifier mismatch')
            if not set(a.get('resolution_evidence_node_ids',[]))<=nodes:raise ValueError('invalid resolution evidence')

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
    from teoria.features.specification_processing.parsing.document_parser import parse_document
    model=runner(request)
    async def parse_one(entry):
        folder=Path(workspace)/'processing'/entry['document_id'];await asyncio.to_thread(folder.mkdir,parents=True,exist_ok=True)
        context=await parse_document(Path(entry['source_path']),folder/'native.json',entry['document_id'],request.parser_python)
        from teoria.features.specification_processing.parsing.document_assessment import assess_document
        assessment=await assess_document(context,model,folder)
        context['document_assessment']=assessment
        await save(folder/'document_assessment.json',assessment)
        await save(folder/'document.json',context)
        if assessment['excluded']:
            entry['failure']={'stage':'document_assessment','reason':'not_specification','disposition':'excluded',
                              'details':{'document_kind':assessment['document_kind']}}
    await each_document(workspace,request,parse_one)

@task(name='02 엔티티·계층·관계 추출',**TASK_OPTIONS)
async def extract_entity_relations(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.entity_relation_extraction import extract_entity_relations as extract
    model=runner(request)
    async def extract_one(entry):
        folder=Path(workspace)/'processing'/entry['document_id']
        await extract(await load(folder/'document.json'),folder/'inventory',model)
    await each_document(workspace,request,extract_one)

@task(name='03 요구조건 추출·누락 구간 재추출',**TASK_OPTIONS)
async def extract_requirements(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.requirement_extraction import extract_requirements as extract
    model=runner(request)
    async def extract_one(entry):
        folder=Path(workspace)/'processing'/entry['document_id']
        await extract(entry['document_id'],folder/'inventory',folder/'attributes',model,None,False,resolve_semantics=False)
    await each_document(workspace,request,extract_one)

@task(name='04 대상·역할·범위 해석',**TASK_OPTIONS)
async def resolve_attribute_semantics(request:SpecificationRun,workspace:str):
    from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics as resolve
    model=runner(request)
    async def resolve_one(entry):
        folder=Path(workspace)/'processing'/entry['document_id'];out=folder/'attributes'
        graph=await load(out/'attribute_graph.json');summary=await load(out/'summary.json')
        semantic=await resolve(await load(folder/'document.json'),graph,graph['attributes'],model,out)
        summary['semantic_resolution']=semantic
        summary['other_requirement_clauses']=sum(r.get('category')=='other' for r in graph.get('requirements',[]) if r.get('observation_type')=='source_clause')
        summary['attributes']=len(graph['attributes'])
        summary['numeric_comparisons']=sum(a['normalized']['comparison_rule']=='numeric_requirement' for a in graph['attributes'])
        summary['unresolved_units']=sum(a['normalized']['unit_status']=='unmapped' for a in graph['attributes'])
        if semantic['unresolved'] or semantic.get('unresolved_scope',0):summary['status']='partial'
        await save(out/'attribute_graph.json',graph);await save(out/'summary.json',summary)
    await each_document(workspace,request,resolve_one)

@task(name='05 추출 결과 검증·저장',**TASK_OPTIONS)
async def persist_extraction(request:SpecificationRun,workspace:str,reused:bool):
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
                'parser':{'name':'kory_parser','version':context['parser_version'],'ocr':False},
                'entities':graph['entities'],'relations':graph['relations'],'held_relations':graph.get('held_relations',[]),'inventory_ids':graph.get('inventory_ids',[]),
                'declared_quantities':graph.get('declared_quantities',[]),'attributes':attributes,
                'requirements':graph.get('requirements',[]),
                'extraction_status':'partial' if summary['status']=='partial' or graph.get('held_relations') or context.get('document_assessment',{}).get('status')=='needs_review' else 'extracted',
                'attribute_input_coverage':summary['input_coverage'],
                'unresolved_extraction':{**{k:summary[k] for k in ['failed_chunks','uncovered_spec_fragments','semantic_resolution','recovery_passes']},
                                         'held_relations':len(graph.get('held_relations',[])),
                                         'coverage_by_kind':summary.get('coverage_by_kind',{}),
                                         'coverage_reasons':summary.get('coverage_reasons',{}),
                                         'repeated_target_mentions':summary.get('repeated_target_mentions',0),
                                         'other_requirement_clauses':summary.get('other_requirement_clauses',0),
                                         'held_relations_by_kind':summary.get('held_relations_by_kind',{})}})
        corpus={'schema_version':'specification_extraction_v1','classification_code':request.classification_code,'documents':documents,'unavailable_documents':failed,
            'extraction_policy':'product_specifications_with_bounded_recovery_and_other_source_clauses'}
    validate_checkpoint(corpus,request,items)
    await save(Path(workspace)/'extracted.json',corpus)
    async with artifact_store(request.artifact_root) as store:
        return (await store.put(run_key(request,'extracted.json'),await asyncio.to_thread((Path(workspace)/'extracted.json').read_bytes))).model_dump()

@task(name='06 표준 사전 관리·연결',**TASK_OPTIONS)
async def resolve_dictionary(request:SpecificationRun,workspace:str,extraction_ref:dict):
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


@task(name='07 표준 의미 적용',**TASK_OPTIONS)
async def select_and_map_standard(request:SpecificationRun,workspace:str,extraction_ref:dict|None=None,dictionary=None):
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
            normalized,candidates=apply_profile(corpus,package,run_id=request.run_id)
            normalized['standard_ref']=request.standard.model_dump()
            normalized['extraction_ref']=extraction_ref
            attach_source_term_alignment(normalized,dictionary)
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
    if request.mode=='standard_management':standard,candidates,normalized=manage_standard(corpus,standard,request.standard.sha256 if request.standard else None)
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
