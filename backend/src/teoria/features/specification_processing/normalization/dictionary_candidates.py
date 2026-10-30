"""Collect source-literal candidates; semantic renaming and fuzzy merging are excluded."""
from teoria.features.semantic_modeling.goods_dictionary.contracts import (
    DictionaryCandidate, DictionaryEvidence, DictionarySource, DictionarySourceNode,
    DictionarySubmission, normalized_source_name, source_literal_definition,
)


def _evidence(source, name, locators=None):
    nodes = [n for n in source.nodes if locators is None or n.locator in locators]
    matching = [n for n in nodes if normalized_source_name(name) in normalized_source_name(n.text)]
    selected = min(matching or nodes or source.nodes, key=lambda n: len(n.text))
    return [DictionaryEvidence(document_id=source.document_id,source_sha256=source.source_sha256,
                               locator=selected.locator,quote=selected.text)]


def _candidate(key, kind, name, source, origin, *, owner=None, owner_name=None, value_kind=None, locators=None):
    return DictionaryCandidate(candidate_key=key,kind=kind,preferred_name=name,
        definition=source_literal_definition(kind,name,owner_name),owner_candidate_key=owner,
        value_kind=value_kind,origin_ref=origin,evidence=_evidence(source,name,locators))


def submission_from_corpus(corpus, *, auto_approve=True):
    sources, candidates = [], []
    for document in corpus['documents']:
        doc_id = document['document_id']
        raw_nodes = document['parsed_document']['nodes']
        source = DictionarySource(document_id=doc_id,source_sha256=document['source']['sha256'],
            parser_version=document['parser']['version'],nodes=[DictionarySourceNode(
                locator=n.get('native_ref') or 'node:'+n['node_id'],text=n['text']) for n in raw_nodes if n['text'].strip()])
        sources.append(source)
        nodes = {n['node_id']:n.get('native_ref') or 'node:'+n['node_id'] for n in raw_nodes}
        owners = {e['id']:e for e in document['entities'] if e.get('kind') in {'product','material','equipment','software'}}
        for item in owners.values():
            evidence_nodes={e['node_id'] for e in item.get('evidence',[]) if e.get('node_id') in nodes}
            locators={nodes[n] for n in evidence_nodes} if evidence_nodes else None
            candidates.append(_candidate(doc_id+':item:'+item['id'],'item_type',item['name'],source,item['id'],locators=locators))
        for attr in document['attributes']:
            if len(attr.get('subject_ids',[])) != 1 or attr['subject_ids'][0] not in owners:
                continue
            # A generated extraction key is not an expression observed in the document.
            name=attr.get('property_raw')
            if not name or not name.strip():
                continue
            item = owners[attr['subject_ids'][0]]
            if attr.get('semantic_scope') in {None,'unknown'} or attr.get('semantic_role') in {None,'unknown'}:
                continue
            value_kind = attr.get('data_type')
            if value_kind not in {'number','text','range','set'}:
                value_kind = 'text'
            ev = attr['evidence']
            node_ids = ev.get('source_node_ids') or [ev.get('node_id')]
            candidates.append(_candidate(doc_id+':property:'+attr['id'],'characteristic',
                name,source,attr['id'],
                owner=doc_id+':item:'+item['id'],owner_name=item['name'],value_kind=value_kind,
                locators={nodes[n] for n in node_ids if n in nodes}))
    return DictionarySubmission(auto_approve=auto_approve,sources=sources,candidates=candidates)
