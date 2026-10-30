"""Default standard management: compare contexts, discover prior evidence, verify one changeset."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
import unicodedata
import httpx
from pydantic import ValidationError

from teoria.features.semantic_modeling.goods_dictionary.contracts import dictionary_checksum, normalized_source_name
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    DictionarySnapshot, approved_dictionary_snapshot, resolve_snapshot,
)
from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
from teoria.features.specification_processing.normalization.dictionary_maintenance import (
    DictionaryProposalError, maintain_dictionary, register_corpus, source_groups,
)
from teoria.features.specification_processing.storage.artifact_store import artifact_store, read_uri
from teoria.features.specification_processing.storage.run_repository import SpecificationRepository
from teoria.integrations.codex import CodexRunner


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


def accepted_contexts(corpus, candidates, decisions, baseline, normalized=None):
    """A historical interpretation is reusable only when it used the current approved revision."""
    by_key={c.candidate_key:c for c in candidates}
    entry_by_key={d['candidate_key']:d.get('entry_id') for d in decisions}
    docs={d['document_id']:d for d in corpus['documents']}
    means={}
    if normalized:
        for d in normalized.get('dictionary_meanings',{}).get('documents',[]):
            for collection in ('entities','attributes'):
                for o in d[collection]:
                    means[(d['document_id'],o['id'])]=o
    contexts={}
    for decision in decisions:
        if decision['status'] not in {'approved','reused'} or not decision.get('entry_id'):continue
        c=by_key[decision['candidate_key']];doc_id=c.evidence[0].document_id;doc=docs[doc_id]
        code=doc.get('classification_code') or corpus.get('classification_code')
        meaning=resolve_snapshot(baseline,[decision['entry_id']],code)['items'][0]
        observation=next(o for o in doc['entities' if c.kind=='item_type' else 'attributes'] if o['id']==c.origin_ref)
        historical=means.get((doc_id,c.origin_ref),{})
        owner_id=None;owner_accepted=True
        if c.owner_candidate_key:
            owner_candidate=by_key[c.owner_candidate_key]
            owner_entry=entry_by_key.get(c.owner_candidate_key)
            owner=resolve_snapshot(baseline,[owner_entry],code)['items'][0] if owner_entry else {}
            owner_id=owner.get('concept_id')
            old_owner=means.get((doc_id,owner_candidate.origin_ref),{})
            owner_accepted=old_owner.get('dictionary_concept_ref')=='dictionary_concept:'+str(owner_id)
        signature=observation_signature(c,observation,code,owner_id)
        contexts.setdefault(str(decision['entry_id']),[]).append({'signature':signature,'meaning':meaning,
            'document_id':doc_id,
            'accepted':historical.get('meaning_status')=='resolved' and meaning['status']=='resolved'
                and historical.get('definition_revision_id')==meaning.get('revision_id') and owner_accepted})
    return contexts


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


def prune_history(corpus, candidates, decisions, entry_ids, source_hashes):
    by_key={c.candidate_key:c for c in candidates};selected={}
    for decision in decisions:
        if str(decision.get('entry_id')) in entry_ids:
            c=by_key[decision['candidate_key']]
            selected.setdefault(c.evidence[0].document_id,{'item_type':set(),'characteristic':set()})[c.kind].add(c.origin_ref)
    result=deepcopy(corpus);result['documents']=[]
    for doc in corpus['documents']:
        if doc['source']['sha256'] not in source_hashes or doc['document_id'] not in selected:continue
        chosen=selected[doc['document_id']];d=deepcopy(doc)
        d['attributes']=[a for a in d['attributes'] if a['id'] in chosen['characteristic']]
        owners=chosen['item_type']|{owner for a in d['attributes'] for owner in a.get('subject_ids',[])}
        d['entities']=[e for e in d['entities'] if e['id'] in owners]
        d['relations']=[r for r in d['relations'] if r['source_id'] in owners and r['target_id'] in owners]
        d['held_relations']=[]
        result['documents'].append(d)
    return result


async def update_standard_dictionary(request, corpus, extraction_ref, *, api=None, repository=None, runner=None):
    if api is None:
        async with GoodsAuthoringClient() as owned:
            return await update_standard_dictionary(request,corpus,extraction_ref,api=owned,repository=repository,runner=runner)
    repo=repository or SpecificationRepository.from_environment()
    runner=runner or CodexRunner(model=request.model,concurrency=request.model_concurrency,timeout=request.model_timeout_seconds)
    prefix='specification_processing/'+request.run_id+'/'
    async with artifact_store(request.artifact_root) as store:
        artifacts=[]
        async def save(name,body):
            ref=await store.put(prefix+name,(json.dumps(body,ensure_ascii=False,indent=2,default=str)+'\n').encode())
            artifacts.append(ref.model_dump());return ref
        async def finish(result):
            result['artifacts']=[*artifacts,*result.get('artifacts',[])]
            ref=await save('dictionary_incremental.json',{k:v for k,v in result.items() if k!='artifacts'})
            result['artifacts'].append(ref.model_dump())
            return result
        await repo.register_extraction(request.run_id,extraction_ref,corpus)
        candidates,decisions=await register_corpus(api,corpus,'dictionary_'+request.run_id+'_scan',auto_approve=request.dictionary_auto_approve)
        entries={str(d['entry_id']) for d in decisions if d.get('entry_id') and d['status'] in {'approved','reused'}}
        baseline=DictionarySnapshot.model_validate(await api.dictionary_meaning('GET','/snapshot'))
        if request.dictionary_baseline:
            raw=await read_uri(request.dictionary_baseline.uri)
            if hashlib.sha256(raw).hexdigest()!=request.dictionary_baseline.sha256:
                raise ValueError('baseline dictionary checksum mismatch')
            expected=approved_dictionary_snapshot(DictionarySnapshot.model_validate_json(raw))
            if expected.checksum!=approved_dictionary_snapshot(baseline).checksum:
                return await finish({'status':'held','reason':'baseline_dictionary_changed','blocked_source_ids':sorted(entries)})
        current=accepted_contexts(corpus,candidates,decisions,baseline)
        asked=[{'source_entry_id':id,'context_sha256':v['signature'],'definition_revision_id':v['meaning']['revision_id']}
               for id,values in current.items() for v in values if v['meaning']['status']=='resolved']
        cached=await repo.find_accepted_contexts(asked)
        accepted={(v['source_entry_id'],v['context_sha256'],v['definition_revision_id']) for v in cached}
        reusable=all(v['meaning']['status']=='resolved' and (id,v['signature'],v['meaning']['revision_id']) in accepted
                     for id,values in current.items() for v in values)
        if reusable and not request.dictionary_reconcile:
            release=approved_dictionary_snapshot(baseline)
            ref=await save('dictionary_release.json',release.model_dump(mode='json'))
            return await finish({'status':'reused','dictionary_standard':{'uri':ref.uri,'sha256':ref.sha256},
                'held_source_ids':[],'reused_contexts':len(entries),'source_registration':dict(Counter(d['status'] for d in decisions))})
        uncertain={id for id,values in current.items() if any(v['meaning']['status']!='resolved' or
            (id,v['signature'],v['meaning']['revision_id']) not in accepted for v in values)}
        related=await api.dictionary_meaning('POST','/related-context',{'source_entry_ids':sorted(entries if request.dictionary_reconcile else uncertain)})
        historical_contexts={};history_refs=[];loaded_hashes=set();context_reports=[];loaded_cases={};case_refs={}
        current_hashes={d['source']['sha256'] for d in corpus['documents']}
        evidence_descriptors={};evidence_bytes={};validation_hashes=set();validation_notices=set()
        for ref in request.dictionary_validation_corpus:
            raw=await read_uri(ref.uri)
            if hashlib.sha256(raw).hexdigest()!=ref.sha256:raise ValueError('validation extraction checksum mismatch')
            validation_docs=json.loads(raw)['documents']
            validation_hashes.update(d['source']['sha256'] for d in validation_docs)
            validation_notices.update(d['notice_number'] for d in validation_docs if d.get('notice_number'))
        for ref in request.dictionary_evidence_corpus:
            raw=await read_uri(ref.uri)
            if hashlib.sha256(raw).hexdigest()!=ref.sha256:raise ValueError('evidence extraction checksum mismatch')
            evidence=json.loads(raw)
            if evidence.get('classification_code')!=corpus.get('classification_code'):
                raise ValueError('evidence classification mismatch')
            hashes={d['source']['sha256'] for d in evidence['documents']}
            if hashes & validation_hashes or any(d.get('notice_number') in validation_notices for d in evidence['documents']):
                raise ValueError('evidence overlaps independent validation')
            evidence_bytes[ref.uri]=raw
            for digest in hashes:
                evidence_descriptors[digest]={'source_sha256':digest,'run_id':request.run_id,
                    'uri':ref.uri,'sha256':ref.sha256,'normalized_uri':None}

        async def load_history(context):
            if context['status']!='ready':return context.get('reason','related_context_stale')
            # The current corpus already supplies these exact source bytes; old file locations
            # are unnecessary for their reassessment (including after a file-store reset).
            hashes={d['source_sha256'] for d in context['documents']}-current_hashes
            if hashes & validation_hashes:return 'historical_evidence_overlaps_validation'
            available=hashes & evidence_descriptors.keys()
            refs=[evidence_descriptors[h] for h in sorted(available)]
            remaining=hashes-available
            if remaining:refs+=await repo.find_extractions(remaining,exclude_run=request.run_id,limit=100)
            if len(refs)>100:return 'historical_context_budget_exceeded'
            missing=hashes-{r['source_sha256'] for r in refs}-current_hashes
            if missing:return 'historical_extraction_reference_missing'
            for descriptor in refs:
                digest=descriptor['source_sha256']
                case=(digest,descriptor['uri'],descriptor['sha256'])
                selected_entries=set(context['source_entry_ids'])
                if selected_entries.issubset(loaded_cases.get(case,set())):continue
                try:raw=evidence_bytes[descriptor['uri']] if descriptor['uri'] in evidence_bytes else await read_uri(descriptor['uri'])
                except (OSError,ValueError,httpx.HTTPError):return 'historical_extraction_unavailable'
                if hashlib.sha256(raw).hexdigest()!=descriptor['sha256']:return 'historical_extraction_checksum_mismatch'
                try:old=json.loads(raw)
                except ValueError:return 'historical_extraction_invalid_json'
                old['documents']=[d for d in old['documents'] if d['source']['sha256']==digest]
                if not old['documents']:return 'historical_extraction_source_mismatch'
                if any(d.get('notice_number') in validation_notices for d in old['documents']):
                    return 'historical_evidence_overlaps_validation'
                old_candidates,old_decisions=await register_corpus(api,old,'dictionary_'+request.run_id+'_history_'+str(len(loaded_hashes)),auto_approve=False)
                normalized=None
                if descriptor.get('normalized_uri'):
                    try:data=await read_uri(descriptor['normalized_uri'])
                    except (OSError,ValueError,httpx.HTTPError):return 'historical_normalization_unavailable'
                    if hashlib.sha256(data).hexdigest()!=descriptor['normalized_sha256']:return 'historical_normalization_checksum_mismatch'
                    try:normalized=json.loads(data)
                    except ValueError:return 'historical_normalization_invalid_json'
                for id,values in accepted_contexts(old,old_candidates,old_decisions,baseline,normalized).items():
                    historical_contexts.setdefault(id,[]).extend(values)
                selected=prune_history(old,old_candidates,old_decisions,set(context['source_entry_ids']),{digest})
                if not selected['documents']:return 'historical_source_observation_missing'
                suffix=dictionary_checksum([case,sorted(selected_entries)])[:16]
                ref=await save('dictionary_history/'+digest+'_'+suffix+'.json',selected)
                case_refs[case]={'uri':ref.uri,'sha256':ref.sha256}
                history_refs[:]=list(case_refs.values());loaded_hashes.add(digest);loaded_cases[case]=selected_entries
                context_reports.append({'source_sha256':digest,'run_id':descriptor['run_id'],
                    'extraction_ref':{'uri':descriptor['uri'],'sha256':descriptor['sha256']}})
            return None
        error=await load_history(related)
        await save('dictionary_related_context.json',{'context':related,'loaded':context_reports,'reason':error})
        needs_review={id for id,values in current.items() if any(v['meaning']['status']!='resolved' or not (
            (id,v['signature'],v['meaning']['revision_id']) in accepted or any(
                h['accepted'] and h['signature']==v['signature'] for h in historical_contexts.get(id,[]))) for v in values)}
        if request.dictionary_reconcile:needs_review=entries
        if error:
            return await finish({'status':'held','reason':error,'blocked_source_ids':sorted(needs_review or entries)})
        if not needs_review:
            release=approved_dictionary_snapshot(baseline)
            ref=await save('dictionary_release.json',release.model_dump(mode='json'))
            return await finish({'status':'reused','dictionary_standard':{'uri':ref.uri,'sha256':ref.sha256},
                'held_source_ids':[],'reused_contexts':len(entries),'source_registration':dict(Counter(d['status'] for d in decisions))})
        for attempt in range(2):
            batch='inc_'+request.run_id[:35]+'_'+hashlib.sha256(request.run_id.encode()).hexdigest()[:8]+'_'+str(attempt)
            try:
                planned=await maintain_dictionary({'batch_id':batch,'artifact_root':request.artifact_root,
                'model':request.model or 'configured_default','auto_apply':False,'model_timeout_seconds':request.model_timeout_seconds,
                'extractions':[{'uri':extraction_ref['uri'],'sha256':extraction_ref['sha256']},*history_refs,
                    *[r.model_dump(mode='json') for r in request.dictionary_corpus]],
                    'validation_extractions':[r.model_dump(mode='json') for r in request.dictionary_validation_corpus]},api=api,runner=runner)
            except ValueError as exc:
                # Persist schema locations/types only: model input and source bodies stay private.
                details=([{'location':list(e['loc']),'type':e['type']} for e in exc.errors()]
                         if isinstance(exc,ValidationError) else [])
                return await finish({'status':'held','reason':'invalid_incremental_change_proposal',
                    'error_type':type(exc).__name__,'validation_errors':details,
                    'validation_rule':exc.code if isinstance(exc,DictionaryProposalError) else None,
                    'blocked_source_ids':sorted(needs_review)})
            if planned['status']=='held':
                change_ref=next((a for a in planned['artifacts'] if a['key'].endswith('/changeset.json')),None)
                if change_ref and attempt==0:
                    raw=await read_uri(change_ref['uri'])
                    if hashlib.sha256(raw).hexdigest()!=change_ref['sha256']:raise ValueError('changeset checksum mismatch')
                    expanded=await api.dictionary_meaning('POST','/related-context',{'changes':json.loads(raw)})
                    before=dictionary_checksum(history_refs);error=await load_history(expanded)
                    if not error and dictionary_checksum(history_refs)!=before:
                        artifacts.extend(planned['artifacts']);continue
                return await finish({**planned,'blocked_source_ids':sorted(needs_review)})
            if request.dictionary_meaning_auto_approve:
                if request.dictionary_require_validation and not planned.get('validation_documents'):
                    return await finish({**planned,'status':'held','reason':'independent_validation_required',
                        'blocked_source_ids':sorted(needs_review)})
                if request.dictionary_max_held_source_ids is not None and len(planned.get('held_source_ids',[]))>request.dictionary_max_held_source_ids:
                    return await finish({**planned,'status':'held','reason':'held_source_limit_exceeded',
                        'blocked_source_ids':sorted(needs_review)})
                change_ref=next(a for a in planned['artifacts'] if a['key'].endswith('/changeset.json'))
                raw=await read_uri(change_ref['uri'])
                if hashlib.sha256(raw).hexdigest()!=change_ref['sha256']:raise ValueError('changeset checksum mismatch')
                applied=await api.dictionary_meaning('POST','/maintenance/maintenance_'+batch,json.loads(raw))
                release=DictionarySnapshot.model_validate(applied.get('release_snapshot',applied['snapshot']))
                ref=await save('dictionary_release.json',release.model_dump(mode='json'))
                planned.update(status='applied',application=applied,dictionary_standard={'uri':ref.uri,'sha256':ref.sha256})
            planned['blocked_source_ids']=planned.get('held_source_ids',[]) if planned['status']=='applied' else sorted(needs_review)
            return await finish(planned)
