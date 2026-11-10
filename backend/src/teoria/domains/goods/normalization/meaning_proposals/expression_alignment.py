"""Register expressions and attach approved connections without changing source observations."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from collections import Counter
import json
import hashlib

from teoria.domains.goods.authoring_client import GoodsAuthoringClient
from teoria.domains.goods.normalization.meaning_proposals.expression_candidates import submission_from_corpus

from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store, read_uri
from teoria.domains.goods.expression_links.snapshot_contracts import resolve_snapshot, parse_dictionary_snapshot


async def _author_legacy_meanings(request, corpus, submission, registration, api):
    """Only legacy direct calls may author local meanings; fixed document runs never do."""
    if request.mode != 'standard_management':
        return {'policy_version':'codex_grounded_meaning_v1', 'model':request.model,
                'auto_approve':request.dictionary_meaning_auto_approve,
                'decisions':[], 'status':'skipped_fixed_standard'}
    from teoria.domains.goods.normalization.legacy_dictionary.semantic_authoring import author_dictionary_meanings as author_legacy
    return await author_legacy(request, corpus, submission, registration, api)


def aligned_observations(corpus, submission, result):
    candidates = {c.candidate_key:c for c in submission.candidates}
    decisions = {}
    for decision in result['decisions']:
        candidate = candidates[decision['candidate_key']]
        key = (candidate.evidence[0].document_id,candidate.kind,candidate.origin_ref)
        decisions[key] = decision
    documents = []
    for document in corpus['documents']:
        row = {'document_id':document['document_id'],'source_sha256':document['source']['sha256'],
               'review_status':'proposed','entities':deepcopy(document['entities']),
               'relations':deepcopy(document['relations']),'attributes':deepcopy(document['attributes'])}
        for kind,collection in [('item_type','entities'),('characteristic','attributes')]:
            for observation in row[collection]:
                decision = decisions.get((document['document_id'],kind,observation['id']))
                observation['source_registration_status'] = decision['status'] if decision else 'unresolved'
                if decision and decision['status'] in {'approved','reused'}:
                    observation['source_term_ref'] = 'source_term:'+decision['entry_id']
        documents.append(row)
    return documents


def apply_concept_meanings(documents, resolution):
    """Attach governed dictionary meanings without rewriting source values or Ontology IDs."""
    by_source={r['source_entry_id']:r for r in resolution['items']}
    aligned=deepcopy(documents)
    counts=Counter()
    for document in aligned:
        for collection in ['entities','attributes']:
            for observation in document[collection]:
                source_id=observation.get('source_term_ref','').removeprefix('source_term:')
                meaning=by_source.get(source_id,{'status':'unresolved','reason':'no_registered_source'})
                observation['meaning_status']=meaning['status']
                observation['meaning_reason']=meaning['reason']
                if meaning['status']=='resolved':
                    if meaning.get('ontology'):
                        observation['ontology_concept_ref'] = meaning['concept_id']
                        observation['ontology'] = meaning['ontology']
                        observation['definition_revision_id'] = meaning['revision_id']
                        observation['meaning_mapping_ids'] = meaning['mapping_ids']
                        # Role/scope/value/unit checks belong to the pinned profile.
                        # An expression link alone never produces a normalized value.
                        counts[observation['meaning_status']] += 1
                        continue
                    observation['dictionary_concept_ref']='dictionary_concept:'+meaning['concept_id']
                    observation['definition_revision_id']=meaning['revision_id']
                    observation['meaning_mapping_ids']=meaning['mapping_ids']
                    if collection=='attributes':
                        definition=meaning['definition']
                        unit=observation.get('unit_raw')
                        observation['value_validation']='unchecked'
                        if definition['allowed_units'] and unit not in definition['allowed_units']:
                            observation['value_validation']='unit_not_allowed'
                        elif definition['value_kind']=='number':
                            try:
                                number=Decimal(str(observation['value_raw']))
                                if not number.is_finite():raise InvalidOperation
                                observation['value_validation']='valid'
                                observation['typed_value']={'decimal':str(number),'unit':unit}
                            except (InvalidOperation,KeyError):
                                observation['value_validation']='invalid_number'
                counts[observation['meaning_status']]+=1
    return {'policy_version':resolution['policy_version'],'snapshot_checksum':resolution.get('snapshot_checksum'),
            'summary':dict(counts),'documents':aligned}


def registration_from_snapshot(corpus, snapshot):
    """Match exact registered source expressions and owners; never register or infer synonyms."""
    from teoria.domains.goods.expression_links.contracts import normalized_source_name
    submission = submission_from_corpus(corpus, auto_approve=False)
    decisions, by_candidate = [], {}
    for candidate in sorted(submission.candidates, key=lambda c: c.kind != 'item_type'):
        owner = by_candidate.get(candidate.owner_candidate_key) if candidate.owner_candidate_key else candidate.owner_entry_id
        matches = [source for source in snapshot.sources
            if source['status'] == 'approved' and source['kind'] == candidate.kind
            and normalized_source_name(source['preferred_name']) == normalized_source_name(candidate.preferred_name)
            and (str(source.get('owner_entry_id')) if source.get('owner_entry_id') else None) == owner]
        if candidate.kind == 'characteristic' and owner is None:
            matches = []
        entry = str(matches[0]['entry_id']) if len(matches) == 1 else None
        by_candidate[candidate.candidate_key] = entry
        decisions.append({'candidate_key': candidate.candidate_key, 'origin_ref': candidate.origin_ref,
            'status': 'reused' if entry else 'held', 'entry_id': entry,
            'reason': 'exact_snapshot_expression' if entry else 'expression_registration_required'})
    return submission, {'operation_id': 'frozen_snapshot', 'policy_version': 'source_literal_v1',
        'approval_mode': 'frozen_snapshot', 'status': 'partial' if any(d['status']=='held' for d in decisions) else 'completed',
        'summary': dict(Counter(d['status'] for d in decisions)), 'decisions': decisions}


def pinned_meanings(corpus, snapshot):
    submission, registration = registration_from_snapshot(corpus, snapshot)
    documents = aligned_observations(corpus, submission, registration)
    source_ids = sorted({d['entry_id'] for d in registration['decisions'] if d['entry_id']})
    resolution = resolve_snapshot(snapshot, source_ids, corpus.get('classification_code'))
    return apply_concept_meanings(documents, resolution), registration


async def align_dictionary(request, corpus, extraction_ref, *, maintenance=None):
    """Called by the existing processing Task, never a separate Flow or mode."""
    operation_id = 'dictionary_'+request.run_id
    async with artifact_store(request.artifact_root) as store:
        artifacts = []
        pinned = None
        if getattr(request,'dictionary_rebuild_from_sources',False):
            from teoria.domains.goods.expression_links.snapshot_contracts import snapshot_from_records
            pinned = snapshot_from_records([], [], [])
        if maintenance is not None:
            artifacts.extend(maintenance['artifacts'])
            standard=maintenance.get('dictionary_standard') or maintenance.get('baseline_dictionary')
            if standard is None and request.dictionary_baseline is not None:
                standard=request.dictionary_baseline.model_dump(mode='json')
            if standard:
                raw=await read_uri(standard['uri'])
                if hashlib.sha256(raw).hexdigest()!=standard['sha256']:
                    raise ValueError('maintenance dictionary checksum mismatch')
                pinned=parse_dictionary_snapshot(raw)
        if request.dictionary_standard:
            raw = await read_uri(request.dictionary_standard.uri)
            if hashlib.sha256(raw).hexdigest()!=request.dictionary_standard.sha256:
                raise ValueError('dictionary standard checksum mismatch')
            pinned = parse_dictionary_snapshot(raw)
            if request.mode=='standard_management':
                raise ValueError('dictionary_standard is read-only; use document_processing')
        if request.mode == 'document_processing' and pinned is None and corpus['documents']:
            # One read pins this execution. Applying observations never writes source registrations.
            async with GoodsAuthoringClient() as api:
                pinned = parse_dictionary_snapshot(await api.dictionary_meaning('GET', '/snapshot'))
        if pinned is not None and pinned.schema_version == 2 and request.standard is not None:
            raw_standard = await read_uri(request.standard.uri)
            if hashlib.sha256(raw_standard).hexdigest() != request.standard.sha256:
                raise ValueError('standard checksum mismatch')
            standard = json.loads(raw_standard)
            if standard.get('artifact_kind') == 'goods_normalization_package':
                from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot_for_publication
                pinned = expression_snapshot_for_publication(pinned, standard['profile']['ontology'])
        if corpus['documents'] and pinned is not None and pinned.schema_version == 2:
            submission, result = registration_from_snapshot(corpus, pinned)
            source_ids = sorted({d['entry_id'] for d in result['decisions'] if d['entry_id']})
            resolution = resolve_snapshot(pinned, source_ids, request.classification_code)
            semantic_authoring = {'status': 'skipped_fixed_standard', 'summary': {}, 'decisions': []}
            documents = aligned_observations(corpus, submission, result)
        elif corpus['documents']:
            submission = submission_from_corpus(corpus,auto_approve=request.dictionary_auto_approve)
            raw=(submission.model_dump_json(indent=2)+'\n').encode()
            artifacts.append((await store.put(f'specification_processing/{request.run_id}/dictionary_candidates.json',raw)).model_dump())
            async with GoodsAuthoringClient() as api:
                result = await api.dictionary(operation_id,submission.model_dump(mode='json'))
                if maintenance is None:
                    semantic_authoring = await _author_legacy_meanings(request,corpus,submission,result,api)
                else:
                    status=maintenance['status']
                    semantic_authoring={'status':status,'maintenance':maintenance,
                        'summary':{'held':1} if status=='held' else {'proposed':1} if status=='proposed' else {
                            'approved':len(maintenance.get('application',{}).get('impact',[])),
                            'held':len(maintenance.get('held_source_ids',[]))},
                        'decisions':[]}
                source_ids=sorted({d['entry_id'] for d in result['decisions'] if d.get('entry_id')})
                # A supplied snapshot freezes definitions AND mappings across repeated document runs.
                # Older Admin installations may continue live resolution until their snapshot API is deployed.
                if pinned is not None:
                    resolution=resolve_snapshot(pinned,source_ids,request.classification_code)
                else:
                    resolution_items=[]
                    policy_version = 'published_ontology_expression_v2'
                    for start in range(0,len(source_ids),1000):
                        resolved=await api.resolve_dictionary_meanings(source_ids[start:start+1000],request.classification_code)
                        policy_version = resolved.get('policy_version', 'approved_scoped_equivalence_v1')
                        resolution_items.extend(resolved['items'])
                    resolution={'policy_version':policy_version,'items':resolution_items}
            documents = aligned_observations(corpus,submission,result)
            blocked=set(maintenance.get('blocked_source_ids',[])) if maintenance else set()
            for meaning in resolution['items']:
                if meaning['source_entry_id'] in blocked:
                    source_id=meaning['source_entry_id']
                    meaning.clear()
                    # Never fall back to an old approved interpretation after its new context was held.
                    meaning.update(source_entry_id=source_id,status='held',reason='incremental_review_pending')
        else:
            result={'operation_id':operation_id,'status':'skipped','policy_version':'source_literal_v1',
                    'approval_mode':'automatic_policy','summary':{'approved':0,'reused':0,'held':0,'proposed':0},'decisions':[]}
            documents=[]
            resolution={'policy_version':'approved_scoped_equivalence_v1','items':[]}
            semantic_authoring={'status':'skipped_empty','summary':{},'decisions':[]}
        payload={'schema_version':1,'extraction_ref':extraction_ref,'dictionary_operation_id':operation_id,
                 'policy_version':result['policy_version'],'semantic_maturity':'source_literal',
                 'human_review_performed':False,'documents':documents,
                 'concept_alignment':apply_concept_meanings(documents,resolution)}
        outputs=[('dictionary_semantic_decisions.json',semantic_authoring),('dictionary_bindings.json',result),('source_term_alignment.json',payload)]
        if pinned is not None:
            outputs.append(('dictionary_standard.json',pinned.model_dump(mode='json')))
            payload['dictionary_snapshot_checksum']=pinned.checksum
        for leaf,body in outputs:
            ref=await store.put(f'specification_processing/{request.run_id}/{leaf}',(json.dumps(body,ensure_ascii=False,indent=2)+'\n').encode())
            artifacts.append(ref.model_dump())
            if leaf=='source_term_alignment.json':alignment_ref=ref.model_dump()
    from teoria.domains.goods.normalization.meaning_proposals.expression_context import context_stamps
    stamps=context_stamps(corpus,submission,result,payload['concept_alignment']) if corpus['documents'] else []
    return {'result':result,'summary':{**result['summary'],'semantic_authoring':semantic_authoring.get('summary',{})},'alignment_ref':alignment_ref,'artifacts':artifacts,'meaning_summary':payload['concept_alignment']['summary'],'meaning_alignment':payload['concept_alignment'],'context_stamps':stamps}
