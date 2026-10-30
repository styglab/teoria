"""03 Requirement extraction with bounded recovery; invokes 04 attribute semantic resolution."""
import asyncio
import hashlib
import json
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
from teoria.features.specification_processing.extraction.attribute_extraction import AttributeBatch,PROMPT,make_chunks,decode_batch,normalize_fact,save


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inventory_attributes(graph):
    result=[]
    kinds={e['id']:e['kind'] for e in graph.get('entities',[])}
    for q in graph.get('declared_quantities',[]):
        raw_unit=q.get('unit_raw');value=q['value_raw']
        result.append({'id':'attribute_'+q['requirement_id'],'subject_ids':[q['entity_id']],'property_key':'quantity','property_raw':None,'data_type':'number',
                       'operator':'eq','operator_raw':None,'value_raw':value,'unit_raw':raw_unit,'qualifiers_raw':[],
                       'normalized':normalize_fact('quantity','number','eq',value,raw_unit),'ontology_property_id':None,'review_status':'needs_review',
                'origin':'validated_inventory_quantity',
                **({'semantic_role':'requirement_candidate','semantic_scope':'batch_total'} if kinds.get(q['entity_id'])=='product' else {}),
                'evidence':{'source_node_ids':q['source_node_ids'],'scope':'explicit inventory target only'}})
    return result



async def extract_requirements(sid,source,out,runner,source_root,verified_parse_only=False,*,resolve_semantics=False):
    started=time.monotonic();document=json.loads((source/'document.json').read_text());graph=json.loads((source/'graph.json').read_text())
    original=Path(document['source_path'])
    if not original.exists() and source_root:original=source_root/original.name
    original_available=original.exists()
    if not original_available and not verified_parse_only:raise FileNotFoundError('Original input unavailable; explicit --verified-parse-only is required to replay saved parser evidence.')
    if original_available and sha(original)!=document['source_sha256']:raise ValueError('original source identity changed')
    parse=Path(document['parse_path'])
    if sha(parse)!=document['native_sha256'] or json.loads(parse.read_text())['sha256']!=document['source_sha256']:raise ValueError('saved parse/source identity changed')
    previous=json.loads((out/'summary.json').read_text()) if (out/'summary.json').exists() else {}
    from teoria.features.specification_processing.extraction.document_context import DocumentContext,pack_fragments
    context=DocumentContext(document)
    from teoria.features.specification_processing.parsing.document_assessment import extraction_node_ids
    eligible=extraction_node_ids(document)
    chunks=make_chunks(graph,document);save(out/'chunks.json',chunks)
    save(out/'input_manifest.json',{'source_graph_path':str((source/'graph.json').resolve()),'source_document_path':str((source/'document.json').resolve()),
         'source_graph_sha256':sha(source/'graph.json'),'source_document_sha256':sha(source/'document.json'),
         'source_verified_path':str(original) if original_available else None,'source_sha256':document['source_sha256'],'original_file_reverified':original_available,'saved_parse_hash_verified':True,'chunks':len(chunks),'graph_entities_changed':False,
         'source_code_sha256':{p.name:sha(p) for p in [ROOT/'attribute_extraction.py',ROOT/'attribute_chunking.py',ROOT/'document_context.py',ROOT/'value_normalization.py',Path(__file__)]},'retries':0,'human_reviewed':False})
    entities=[[e['id'],e['name'],e['kind']] for e in graph['entities']]
    async def one(index,chunk,recovery=False):
        path=out/('recovery' if recovery else 'inference')/f'chunk_{index:02}.json';before=time.monotonic();cache_hit=path.exists()
        try:
            from teoria.features.specification_processing.extraction.attribute_validation import fragment_context
            contexts={f['id']:fragment_context(document,f,context=context) for f in chunk}
            context_texts={row[0]:row[3] for rows in contexts.values() for row in rows}
            request={'document_id':sid,'entities':entities,'fragments':[[f['id'],f['node_id'],f['suggested_subject_ids'],f['text']] for f in chunk],
                     'fragment_groups':{f['id']:f['context_group'] for f in chunk},
                     'node_context':{key:[row[0] for row in rows] for key,rows in contexts.items()},
                     'context_nodes':[[n['node_id'],n['kind'],n.get('parent_id'),n.get('source_table_id'),n.get('row'),n.get('column'),n.get('row_span'),n.get('column_span'),context_texts[n['node_id']]]
                                      for n in document['nodes'] if n['node_id'] in context_texts],
                     'relation_context':[[r['source_id'],r['kind'],r['target_id']] for r in graph['relations']],
                     'passage_roles':{f['node_id']:document.get('document_assessment',{}).get('node_roles',{}).get(f['node_id'],'unknown') for f in chunk},
                     'attempt':'missing_fragment_recovery' if recovery else 'initial',
                     'output_schema':AttributeBatch.model_json_schema()}
            raw=await runner.generate(PROMPT,request,path)
            if not isinstance(raw.get('facts'),list):raise ValueError('missing facts array')
            accepted,quarantine,unresolved=decode_batch(raw,chunk,graph,document,index)
            result={'chunk':index,'status':'needs_review' if not quarantine else 'partial','attributes':accepted,'quarantined':quarantine,
                    'unresolved':unresolved,'seconds':round(time.monotonic()-before,2)}
        except Exception as exc:result={'chunk':index,'status':'failed','error':type(exc).__name__+': '+str(exc),'attributes':[],'quarantined':[],'unresolved':[],'seconds':round(time.monotonic()-before,2)}
        result['cache_hit']=cache_hit
        save(out/'batches'/f'chunk_{index:02}.json',result)
        return result
    batches=await asyncio.gather(*(one(index,chunk) for index,chunk in enumerate(chunks)))
    from teoria.features.specification_processing.extraction.attribute_validation import uncovered,deduplicate_inventory
    initial_attributes=[a for b in batches for a in b['attributes']]
    gaps=uncovered(chunks,initial_attributes,graph=graph)
    recovery_chunks=pack_fragments(gaps,context)
    recovered=await asyncio.gather(*(one(len(chunks)+i,chunk,True) for i,chunk in enumerate(recovery_chunks)))
    batches+=recovered
    extracted=[a for b in batches for a in b['attributes']]
    inventory=inventory_attributes(graph)
    extracted,duplicates=deduplicate_inventory(inventory,extracted)
    attributes=inventory+extracted
    remaining=uncovered(chunks,attributes,[d['evidence']['fragment_id'] for d in duplicates],graph=graph)
    semantic={'resolved':0,'unresolved':0,'reassigned':0}
    if resolve_semantics:
        from teoria.features.specification_processing.extraction.attribute_resolution import resolve_attribute_semantics
        semantic=await resolve_attribute_semantics(document,graph,attributes,runner,out)
    quarantined=[a for b in batches for a in b['quarantined']]
    unresolved=[a for b in batches for a in b['unresolved']]
    extracted_fragments={a['evidence']['fragment_id'] for a in attributes if 'fragment_id' in a['evidence']}
    all_fragments=[f for chunk in chunks for f in chunk]
    coverage=[{'fragment_id':f['id'],'node_id':f['node_id'],'status':'attributes_returned' if f['id'] in extracted_fragments else 'no_attribute_returned',
               'contains_digits':any(c.isdigit() for c in f['text'])} for f in all_fragments]
    summary={'document_id':sid,'status':'partial' if quarantined or remaining or semantic['unresolved'] or semantic.get('unresolved_scope',0) or (bool(chunks) and not extracted) or any(b['status']=='failed' for b in batches) else 'needs_review',
             'attributes':len(attributes),'inventory_quantity_attributes':len(inventory_attributes(graph)),'new_model_attributes':sum(len(b['attributes']) for b in batches),
             'input_coverage':{'excluded_node_ids':[n['node_id'] for n in document['nodes'] if n['node_id'] not in eligible],'available_nodes':sum(n['node_id'] in eligible and bool(n['text'].strip()) and n['kind']!='image' for n in document['nodes']),'forwarded_nodes':len({f['node_id'] for c in chunks for f in c}),'missing_node_ids':[n['node_id'] for n in document['nodes'] if n['node_id'] in eligible and n['text'].strip() and n['kind']!='image' and n['node_id'] not in {f['node_id'] for c in chunks for f in c}]},'quarantined':len(quarantined),'recovery_passes':int(bool(recovery_chunks)),'recovery_chunks':len(recovery_chunks),'uncovered_spec_fragments':len(remaining),'zero_detail_attributes':not bool(extracted),'semantic_resolution':semantic,'inventory_quantity_duplicates':len(duplicates),'failed_chunks':sum(b['status']=='failed' for b in batches),'chunks':len(chunks),
             'numeric_comparisons':sum(a['normalized']['comparison_rule']=='numeric_requirement' for a in attributes),
             'unresolved_units':sum(a['normalized']['unit_status']=='unmapped' for a in attributes),
             'new_model_calls':sum(not b['cache_hit'] for b in batches),'wire_format_projections':sum(bool(a.get('wire_format_projection')) for a in attributes),
             'seconds':previous.get('seconds',round(time.monotonic()-started,2)) if all(b['cache_hit'] for b in batches) else round(time.monotonic()-started,2),
             'postprocess_seconds':round(time.monotonic()-started,2),'human_reviewed':False}
    from collections import Counter
    summary['coverage_by_kind']=dict(Counter(f.get('expected_role','unknown') for f in remaining))
    summary['held_relations_by_kind']=dict(Counter(r['kind'] for r in graph.get('held_relations',[])))
    save(out/'attributes.json',attributes);save(out/'quarantined.json',quarantined);save(out/'unresolved.json',unresolved)
    save(out/'coverage.json',{'fragments':coverage,'uncovered_spec_fragment_ids':[f['id'] for f in remaining],'inventory_duplicates':duplicates,'remaining_by_kind':summary['coverage_by_kind'],'is_recall_measure':False});save(out/'summary.json',summary)
    save(out/'attribute_graph.json',{**graph,'attributes':attributes})
    return summary

