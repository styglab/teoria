"""Stage 06: register expressions, author unresolved meanings, resolve approved mappings."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from collections import Counter
import json
import hashlib

from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
from teoria.features.specification_processing.normalization.dictionary_candidates import submission_from_corpus
from teoria.features.specification_processing.normalization.dictionary_semantics import author_dictionary_meanings
from teoria.features.specification_processing.storage.artifact_store import artifact_store, read_uri
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import DictionarySnapshot, resolve_snapshot


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


async def align_dictionary(request, corpus, extraction_ref, *, maintenance=None):
    """Called by the existing processing Task, never a separate Flow or mode."""
    operation_id = 'dictionary_'+request.run_id
    async with artifact_store(request.artifact_root) as store:
        artifacts = []
        pinned = None
        if maintenance is not None:
            artifacts.extend(maintenance['artifacts'])
            standard=maintenance.get('dictionary_standard')
            if standard:
                raw=await read_uri(standard['uri'])
                if hashlib.sha256(raw).hexdigest()!=standard['sha256']:
                    raise ValueError('maintenance dictionary checksum mismatch')
                pinned=DictionarySnapshot.model_validate_json(raw)
        if request.dictionary_standard:
            raw = await read_uri(request.dictionary_standard.uri)
            if hashlib.sha256(raw).hexdigest()!=request.dictionary_standard.sha256:
                raise ValueError('dictionary standard checksum mismatch')
            pinned = DictionarySnapshot.model_validate_json(raw)
            if request.mode=='standard_management':
                raise ValueError('dictionary_standard is read-only; use document_processing')
        if corpus['documents']:
            submission = submission_from_corpus(corpus,auto_approve=request.dictionary_auto_approve)
            raw=(submission.model_dump_json(indent=2)+'\n').encode()
            artifacts.append((await store.put(f'specification_processing/{request.run_id}/dictionary_candidates.json',raw)).model_dump())
            async with GoodsAuthoringClient() as api:
                result = await api.dictionary(operation_id,submission.model_dump(mode='json'))
                if maintenance is None:
                    semantic_authoring = await author_dictionary_meanings(request,corpus,submission,result,api)
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
                    for start in range(0,len(source_ids),1000):
                        resolved=await api.resolve_dictionary_meanings(source_ids[start:start+1000],request.classification_code)
                        resolution_items.extend(resolved['items'])
                    resolution={'policy_version':'approved_scoped_equivalence_v1','items':resolution_items}
            documents = aligned_observations(corpus,submission,result)
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
    return {'result':result,'summary':{**result['summary'],'semantic_authoring':semantic_authoring.get('summary',{})},'alignment_ref':alignment_ref,'artifacts':artifacts,'meaning_summary':payload['concept_alignment']['summary'],'meaning_alignment':payload['concept_alignment']}
