"""Collect grounded review candidates; never author another local meaning model."""
import json
from collections import Counter

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    approved_dictionary_snapshot, resolve_snapshot,
)
from teoria.features.specification_processing.normalization.dictionary_semantics import observation_context
from teoria.features.specification_processing.storage.artifact_store import artifact_store


async def collect_ontology_candidates(baseline, corpus, candidates, decisions, *, artifact_root, prefix):
    snapshot = approved_dictionary_snapshot(baseline)
    by_key = {c.candidate_key: c for c in candidates}
    contexts = {c['candidate']['candidate_key']: c for c in observation_context(corpus, candidates)}
    codes = {d['document_id']: d.get('classification_code') or corpus.get('classification_code') for d in corpus['documents']}
    unresolved = []
    for decision in decisions:
        candidate = by_key[decision['candidate_key']]
        source = decision.get('entry_id')
        meaning = (resolve_snapshot(snapshot, [source], codes[candidate.evidence[0].document_id])['items'][0]
                   if source else {'status': 'unresolved', 'reason': 'source_not_registered'})
        if meaning['status'] != 'resolved':
            unresolved.append({'source_entry_id': source, 'status': 'proposed',
                'reason': meaning['reason'], 'classification_code': codes[candidate.evidence[0].document_id],
                **contexts[candidate.candidate_key]})
    report = {'schema_version': 1, 'artifact_kind': 'goods_ontology_review_candidates',
              'authority': 'suggestion', 'reason': 'ontology_review_required',
              'auto_approve': False, 'candidates': unresolved}
    async with artifact_store(artifact_root) as store:
        artifacts = []
        for name, body in [('ontology_candidates.json', report), ('dictionary_release.json', snapshot.model_dump(mode='json'))]:
            ref = await store.put(prefix + name, (json.dumps(body, ensure_ascii=False, indent=2) + '\n').encode())
            artifacts.append(ref.model_dump(mode='json'))
            if name == 'dictionary_release.json':
                release = {'uri': ref.uri, 'sha256': ref.sha256}
    return {'status': 'proposed' if unresolved else 'reused', 'reason': 'ontology_review_required' if unresolved else 'approved_ontology_links',
            'summary': dict(Counter(c['status'] for c in unresolved)), 'auto_applied': False,
            'dictionary_standard': release, 'artifacts': artifacts, 'held_source_ids': [],
            'candidate_count': len(unresolved), 'blocked_source_ids': []}
