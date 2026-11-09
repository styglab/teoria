"""Independent processing outcomes; registration never establishes business meaning.

These are final-stage observations, not a replacement for the legacy run status
or for the owner's approval lifecycle. Historical runs without them stay unknown.
"""
from typing import Literal

from pydantic import BaseModel

from pydantic import ConfigDict

from pydantic import Field


class StageOutcome(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['completed', 'partial', 'failed', 'excluded', 'not_requested',
                    'not_applicable', 'review_required', 'resolved']
    counts: dict[str, int] = Field(default_factory=dict)


class ApplicationOutcome(StageOutcome):
    basis: Literal['pinned_profile', 'fixed_extraction_rules', 'extraction_draft']


class ProcessingStages(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    extraction: StageOutcome
    expression_registration: StageOutcome
    meaning: StageOutcome
    application: ApplicationOutcome


def processing_stages(request, corpus, dictionary, normalized, alignment=None) -> ProcessingStages:
    """Summarize existing evidence without changing observations or granting approvals."""
    documents = corpus['documents']
    unavailable = corpus['unavailable_documents']
    failed = sum(d.get('disposition') != 'excluded' for d in unavailable)
    excluded = len(unavailable) - failed
    partial = sum(d.get('extraction_status') == 'partial' for d in documents)
    extraction = ('partial' if failed or partial else 'completed') if documents else (
        'failed' if failed else 'excluded')

    registration = (dictionary or {}).get('result', {}).get('summary', {})
    registration_status = 'not_requested' if dictionary is None else (
        'not_applicable' if not documents else
        'review_required' if registration.get('held', 0) or registration.get('proposed', 0)
        else 'completed')

    # Expression approval and extraction-rule approval are not meaning approval.
    meanings = (dictionary or {}).get('meaning_summary', {})
    authoring = (dictionary or {}).get('summary', {}).get('semantic_authoring', {})
    comparisons = len((alignment or {}).get('report', {}).get('observations', []))
    unresolved = sum(count for name, count in meanings.items() if name != 'resolved')
    pending = sum(authoring.get(name, 0) for name in ('held', 'proposed'))
    meaning_status = ('not_applicable' if not documents else
                      'review_required' if unresolved or pending or comparisons else
                      'resolved' if meanings.get('resolved', 0) else
                      'not_requested' if dictionary is None and alignment is None else 'not_applicable')

    # Attributes, entities and relations each have their own application outcome.
    applied = sum(normalized.get(key, {}).get('applied', 0)
                  for key in ('summary', 'entity_summary', 'relation_summary'))
    deferred = sum(normalized.get(key, {}).get('automatically_deferred', 0)
                   for key in ('summary', 'entity_summary', 'relation_summary'))
    application_status = 'partial' if deferred else 'completed' if applied else 'not_applicable'
    # A package reference identifies the applied basis, not a new approval decision.
    basis = ('pinned_profile' if normalized.get('artifact_kind') == 'goods_normalized_observations'
             else 'fixed_extraction_rules' if request.mode == 'document_processing'
             else 'extraction_draft')
    return ProcessingStages(
        extraction=StageOutcome(status=extraction, counts={
            'documents': len(documents), 'partial_documents': partial,
            'failed_documents': failed, 'excluded_documents': excluded}),
        expression_registration=StageOutcome(status=registration_status, counts=registration),
        meaning=StageOutcome(status=meaning_status, counts={
            'resolved_observations': meanings.get('resolved', 0),
            'unresolved_observations': unresolved, 'pending_authoring': pending,
            'comparison_observations': comparisons}),
        application=ApplicationOutcome(status=application_status, basis=basis,
                                       counts={'applied': applied, 'deferred': deferred}),
    )
