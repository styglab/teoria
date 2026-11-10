"""Observable source quality and explicit limits for automatic extraction-standard approval."""
import hashlib
import json
from teoria.domains.goods.contracts import AutomaticApprovalLimits


def processing_quality(request,corpus,normalization,revision):
    available=corpus['documents'];failed=[d for d in corpus['unavailable_documents'] if d.get('disposition')!='excluded']
    accepted=sum(len(d['attributes']) for d in available)
    quarantined=sum(len(d.get('quarantined_attributes',[])) for d in available)
    held=int(normalization.get('automatically_deferred',0))
    applied=int(normalization.get('applied',0))+int(normalization.get('applied_composition',0))
    hashes=sorted(d['source']['sha256'] for d in available+corpus['unavailable_documents'])
    return {'schema_version':1,'scope':'operational_conformance','accuracy_measured':False,'processor_revision':revision,'model_requested':request.model,'classification_code':request.classification_code,
        'parser_versions':sorted({d['parser']['version'] for d in available}),
        'source_group_sha256':hashlib.sha256(json.dumps(hashes).encode()).hexdigest(),
        'documents':len(available)+len(failed),'successful_documents':len(available),'failed_documents':len(failed),
        'accepted_attributes':accepted,'quarantined_attributes':quarantined,
        'validation_errors':quarantined+sum(str(d.get('code','')).endswith('_validation_failed') or str(d.get('code','')).startswith('source_numeric_') for d in failed),
        'applied_attributes':applied,'held_attributes':held,
        'failed_document_ratio':len(failed)/max(1,len(available)+len(failed)),
        'held_attribute_ratio':held/max(1,held+applied)}


def automatic_approval_quality(quality,limits,baseline=None):
    if quality is None:return {'ready':False,'reasons':['quality_metrics_missing'],'limits':limits.model_dump()}
    reasons=[]
    if quality.get('applied_attributes',0)<1:reasons.append('no_applied_attributes')
    if quality.get('successful_documents',0)<1:reasons.append('no_successful_documents')
    if quality.get('validation_errors',0)>limits.max_validation_errors:reasons.append('source_validation_errors')
    if quality['failed_document_ratio']>limits.max_failed_document_ratio:reasons.append('failed_document_ratio')
    if quality['held_attribute_ratio']>limits.max_held_attribute_ratio:reasons.append('held_attribute_ratio')
    drift=None
    compatible=baseline and quality.get('model_requested') and all(
        baseline.get(key)==quality.get(key) for key in ('source_group_sha256','model_requested','parser_versions','classification_code'))
    if compatible and baseline.get('accepted_attributes',0)>0:
        drift=abs(quality['accepted_attributes']-baseline['accepted_attributes'])/baseline['accepted_attributes']
        if limits.max_attribute_count_change_ratio is not None and drift>limits.max_attribute_count_change_ratio:
            reasons.append('attribute_count_change_ratio')
    return {'ready':not reasons,'scope':'operational_conformance','accuracy_verified':False,'reasons':reasons,'limits':limits.model_dump(),
        'attribute_count_change_ratio':drift,'baseline_run_id':baseline.get('run_id') if compatible else None}
