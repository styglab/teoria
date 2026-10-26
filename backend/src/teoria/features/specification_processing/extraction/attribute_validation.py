"""Source handoff, completeness signals and exact inventory quantity deduplication."""
import re
import json
from teoria.features.specification_processing.extraction.document_context import DocumentContext

# Broad recovery signals, never an allowlist of product/component names. All text is forwarded first.
SPEC = re.compile(r'\d\s*(?:[A-Za-zµμΩ℃℉°%][A-Za-z0-9µμΩ℃℉°%/·²³^_-]*|개|대|회|년|개월|시간|분|초)|(?:이상|이하|초과|미만|필수|요구|하여야|해야|가능|지원|설치|납품|보증|무상|교육)',re.I)

def is_spec(text):
    return bool(SPEC.search(text))


def fragment_context(document,fragment,*,context=None):
    context=context or DocumentContext(document)
    node_id=fragment['node_id']
    ancestors={n['node_id'] for n in context.ancestors(node_id)}
    headings=set(context.paths[node_id])
    cell=context.cells.get(node_id)
    selected=ancestors|headings
    if cell is not None:
        table=context.table_key(cell)
        selected.update(key for key in context.related_ids(node_id)
                        if key in context.cells and table is not None and context.table_key(context.cells[key])==table)
    else:
        # Initial extraction needs local continuation, not every clause in a whole section.
        siblings=[key for key in context.sections[context.paths[node_id]]
                  if context.lookup[key].get('parent_id')==context.lookup[node_id].get('parent_id')]
        position=siblings.index(node_id)
        selected.update(siblings[max(0,position-1):position+2])
    selected.discard(node_id)
    rows=[n for n in document['nodes'] if n['node_id'] in selected and n['text'].strip()]
    # Retain the previous extraction context limits; full primary fragments stay unchanged.
    rows=sorted(rows,key=lambda n:n['node_id'] not in headings)[:8]
    return [[n['node_id'],n.get('row'),n.get('column'),n['text'][:1000]] for n in rows]


def uncovered(chunks,attributes,additional_covered=()):
    covered=set(additional_covered)|{a['evidence']['fragment_id'] for a in attributes if 'fragment_id' in a.get('evidence',{})}
    return [f for chunk in chunks for f in chunk if is_spec(f['text']) and f['id'] not in covered]


def deduplicate_inventory(inventory,attributes):
    """Only exact generic quantity duplicates. Component counts remain distinct observations."""
    kept=[];duplicates=[]
    for a in attributes:
        match=next((q for q in inventory if a['property_key']=='quantity' and a['subject_ids']==q['subject_ids'] and a['value_raw']==q['value_raw'] and a['unit_raw']==q['unit_raw'] and a['operator']=='eq' and not a['qualifiers_raw'] and a['evidence']['node_id'] in q['evidence']['source_node_ids']),None)
        if match:
            duplicates.append({'attribute_id':a['id'],'duplicate_of':match['id'],'evidence':a['evidence']})
        else:kept.append(a)
    return kept,duplicates


def deduplicate_resolved_attributes(attributes):
    """Merge identical resolved observations only when their full source evidence also agrees."""
    kept=[];seen={};removed=0
    fields=('property_key','property_raw','data_type','operator','operator_raw','value_raw','unit_raw',
            'qualifiers_raw','assertion_kind','modality','review_status','semantic_role','semantic_scope','origin','evidence')
    for a in attributes:
        if not a.get('subject_ids') or a.get('semantic_role') in {None,'unknown'} or not a.get('evidence',{}).get('node_id'):
            kept.append(a);continue
        signature={k:a.get(k) for k in fields}
        signature['subject_ids']=sorted(set(a['subject_ids']))
        signature['resolution_evidence_node_ids']=sorted(set(a.get('resolution_evidence_node_ids',[])))
        key=json.dumps(signature,sort_keys=True,ensure_ascii=False)
        if key not in seen:
            seen[key]=a;kept.append(a);continue
        original=seen[key]
        def origins(row):
            return row.get('merged_observations',[{'attribute_id':row['id'],
                        'extraction_subject_ids':row.get('extraction_subject_ids',row['subject_ids'])}])
        original['merged_observations']=[*origins(original),*origins(a)]
        removed+=1
    attributes[:]=kept
    return removed
