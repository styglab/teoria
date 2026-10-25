"""Source handoff, completeness signals and exact inventory quantity deduplication."""
import re
import json

# Broad recovery signals, never an allowlist of product/component names. All text is forwarded first.
SPEC = re.compile(r'\d\s*(?:[A-Za-zµμΩ℃℉°%][A-Za-z0-9µμΩ℃℉°%/·²³^_-]*|개|대|회|년|개월|시간|분|초)|(?:이상|이하|초과|미만|필수|요구|하여야|해야|가능|지원|설치|납품|보증|무상|교육)',re.I)

def is_spec(text):
    return bool(SPEC.search(text))


def fragment_context(document,fragment):
    nodes=document['nodes'];lookup={n['node_id']:n for n in nodes};node=lookup[fragment['node_id']]
    context=[]
    if node.get('source_table_id') is not None:
        for n in nodes:
            if n['node_id']==node['node_id'] or n.get('source_table_id')!=node['source_table_id']:continue
            if n.get('row')==node.get('row') or (n.get('column')==node.get('column') and n.get('row') is not None and node.get('row') is not None and n['row']<node['row']):
                context.append(n)
    elif node.get('parent_id') in lookup:
        context.append(lookup[node['parent_id']])
    return [[n['node_id'],n.get('row'),n.get('column'),n['text'][:1000]] for n in context[-8:]]


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
