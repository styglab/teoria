"""Source context and reuse fingerprints; no authoring writes or inference."""
import re
import unicodedata

from teoria.domains.goods.expression_links.contracts import dictionary_checksum, normalized_source_name
from teoria.domains.goods.data_processing.extraction.value_normalization import UNITS

def observed_unit_literals(observation, value_kind=None):
    """Read explicit units, including two numeric range endpoints; never convert values."""
    if observation.get('unit_raw'):
        return {observation['unit_raw']}
    if (value_kind or observation.get('value_kind') or observation.get('data_type'))!='range':
        return set()
    unit_pattern='|'.join(re.escape(u) for u in sorted(UNITS,key=len,reverse=True) if UNITS[u] is not None)
    numeric=r'[+-]?(?:\d+(?:,\d{3})*)(?:\.\d+)?'
    match=re.fullmatch(rf'\s*{numeric}\s*({unit_pattern})\s*(?:~|～|–|—|-|to)\s*{numeric}\s*({unit_pattern})\s*',
        observation.get('value_raw') or '')
    return {match[1],match[2]} if match else set()


def observation_context(corpus, candidates):
    documents = {d['document_id']: d for d in corpus['documents']}
    result = []
    for candidate in candidates:
        document = documents[candidate.evidence[0].document_id]
        collection = 'entities' if candidate.kind == 'item_type' else 'attributes'
        observation = next(o for o in document[collection] if o['id'] == candidate.origin_ref)
        owners = [e for e in document['entities'] if e['id'] in observation.get('subject_ids', [])]
        nodes = document['parsed_document']['nodes']
        by_id = {n['node_id']: n for n in nodes}
        required = set(observation.get('resolution_evidence_node_ids', []))
        for item in [observation, *owners]:
            evidence = item.get('evidence', [])
            for ev in evidence if isinstance(evidence, list) else [evidence]:
                required.update(ev.get('source_node_ids', []))
                if ev.get('node_id'):
                    required.add(ev['node_id'])
        # The owner/scope references must carry their actual source text, not only extraction IDs.
        for node_id in list(required):
            parent = by_id.get(node_id, {}).get('parent_id')
            while parent and parent not in required:
                required.add(parent)
                parent = by_id.get(parent, {}).get('parent_id')
        selected = set(required)
        for index, node in enumerate(nodes):
            if node['node_id'] in required:
                selected.update(n['node_id'] for n in nodes[max(0,index-1):index+2])
        result.append({'candidate': candidate.model_dump(mode='json'), 'observation': observation,
                       'owners': owners, 'source_context': [n for n in nodes if n['node_id'] in selected]})
    return result


def observation_signature(candidate, observation, classification_code,owner_concept_id=None):
    """Ignore numeric differences while preserving wording and semantic context."""
    return dictionary_checksum({'kind':candidate.kind,'name':normalized_source_name(candidate.preferred_name),
        'value_kind':candidate.value_kind,'classification_code':classification_code,'owner_concept_id':owner_concept_id,
        'role':observation.get('semantic_role'),'scope':observation.get('semantic_scope'),
        'qualifiers':observation.get('qualifiers_raw',[]),
        'source_context_shape':sorted({re.sub(r'\d+(?:[.,]\d+)*','#',' '.join(
            unicodedata.normalize('NFKC',e.quote).split())) for e in candidate.evidence}),
        'unit':observation.get('unit_raw'),
        'entity_kind':observation.get('kind'),'entity_roles':observation.get('document_roles',[])})


def context_stamps(corpus,submission,registration,alignment):
    """Only references/digests enter the Data DB; observations remain in artifacts."""
    candidates={c.candidate_key:c for c in submission.candidates}
    docs={d['document_id']:d for d in corpus['documents']}
    meanings={(d['document_id'],o['id']):o for d in alignment['documents'] for name in ('entities','attributes') for o in d[name]}
    stamps=[]
    for decision in registration['decisions']:
        candidate=candidates[decision['candidate_key']];doc_id=candidate.evidence[0].document_id;d=docs[doc_id]
        meaning=meanings.get((doc_id,candidate.origin_ref),{})
        if meaning.get('meaning_status')!='resolved':continue
        owner_id=None
        if candidate.owner_candidate_key:
            owner=candidates[candidate.owner_candidate_key]
            owner_id=meanings.get((doc_id,owner.origin_ref),{}).get('dictionary_concept_ref','').removeprefix('dictionary_concept:')
            if not owner_id:continue
        observation=next(o for o in d['entities' if candidate.kind=='item_type' else 'attributes'] if o['id']==candidate.origin_ref)
        stamps.append({'document_id':doc_id,'source_entry_id':str(decision['entry_id']),
            'context_sha256':observation_signature(candidate,observation,d.get('classification_code') or corpus.get('classification_code'),owner_id),
            'definition_revision_id':meaning['definition_revision_id']})
    return stamps

