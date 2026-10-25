"""Collect and select extraction-standard proposals; never publish Business Ontology."""
from copy import deepcopy
import hashlib
from teoria.features.specification_processing.normalization.candidate_collection import collect_meaning_candidates
from teoria.features.specification_processing.models import ContextBinding,PropertyBinding,StandardArtifact
from teoria.features.specification_processing.normalization.standard_application import canonical,map_standard,signature,binding_signature
from teoria.features.specification_processing.normalization.candidate_selection import select_definition


def manage_standard(corpus,baseline:StandardArtifact|None=None,parent_sha256=None):
    baseline=baseline or StandardArtifact(version='initial',classification_code=corpus['classification_code'],definitions=[],bindings=[])
    initial=map_standard(corpus,baseline)
    # Candidate collection consumes the still-unmapped universe, not an artificial failure score.
    projection={'attributes':[{**r,'status':'pending_definition' if r['status']=='automatically_deferred' else r['status']} for r in initial['attributes']]}
    candidates=collect_meaning_candidates(corpus,projection,baseline.model_dump())
    definitions={d['id']:deepcopy(d) for d in baseline.definitions}
    bindings={binding_signature(b):b.model_copy(deep=True) for b in baseline.bindings}
    observations={(d['document_id'],a['id']):(d,a) for d in corpus['documents'] for a in d['attributes']}
    for candidate in candidates['candidates']:
        adopted=0;held=0;reasons={}
        for ref in candidate['observations']:
            doc,a=observations[(ref['document_id'],ref['attribute_id'])]
            choice,kind,reason=select_definition(candidate,doc,a,baseline.rule_set)
            if choice is None:
                held+=1;reasons[reason]=reasons.get(reason,0)+1;continue
            pid=choice.get('property_id',choice.get('definition',{}).get('id'))
            definition=choice.get('definition')
            if definition is not None:
                if pid in definitions and canonical(definitions[pid])!=canonical(definition):held+=1;continue
                definitions[pid]=definition
            context=signature(doc,a,baseline.rule_set)
            binding=ContextBinding(target_types=list(context[0]),property_key=context[1],unit_context=context[2],data_type=context[3],role=context[4],semantic_scope=context[5],
                properties=[PropertyBinding(property_id=pid,rule_kind=kind,candidate={k:candidate[k] for k in ['concept_key','target_type_candidate','scope','role','decision','existing_definition_id']})])
            if context in bindings and bindings[context].properties!=binding.properties:held+=1;continue
            bindings[context]=binding;adopted+=1
        candidate['automatic_resolution']={'adopted':adopted,'deferred':held,'reasons':reasons,'human_approval_required':False}
    draft={'rule_set':baseline.rule_set,'classification_code':corpus['classification_code'],'parent_standard_sha256':parent_sha256,'definitions':sorted(definitions.values(),key=lambda d:d['id']),
        'bindings':[b.model_dump() for _,b in sorted(bindings.items(),key=lambda x:str(x[0]))]}
    version='proposal_'+hashlib.sha256(canonical(draft)).hexdigest()[:20]
    standard=StandardArtifact(version=version,**draft)
    candidates['selection_mode']='automatic_without_human_gate'
    return standard,candidates,map_standard(corpus,standard)
