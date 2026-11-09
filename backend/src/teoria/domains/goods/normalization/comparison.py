"""Compare explicit goods requirements with values for a reviewed subject pairing."""
from decimal import Decimal, InvalidOperation

from teoria.platform.ontology.authoring.observations import SemanticObservation


def compare_property_observations(requirement, candidate, *, subject_links=frozenset()):
    requirement = SemanticObservation.model_validate(requirement)
    candidate = SemanticObservation.model_validate(candidate)
    result = {'status':'held','requirement_observation_id':requirement.observation_id,
              'candidate_observation_id':candidate.observation_id}
    if requirement.information_kind != 'requirement' or candidate.information_kind not in {'declared_value','measurement'}:
        return {**result,'reason':'incompatible_information_kind'}
    if requirement.ontology != candidate.ontology or requirement.concept_id != candidate.concept_id:
        return {**result,'reason':'different_published_concept'}
    if requirement.scope != candidate.scope:
        return {**result,'reason':'different_scope'}
    if requirement.conditions or candidate.conditions:
        return {**result,'reason':'condition_review_required'}
    if len(requirement.subject_refs) != 1 or len(candidate.subject_refs) != 1:
        return {**result,'reason':'single_subject_comparison_required'}
    if not all(any((left,right) in subject_links for right in candidate.subject_refs) for left in requirement.subject_refs):
        return {**result,'reason':'reviewed_subject_link_required'}
    if candidate.information_kind == 'measurement' and candidate.effective_at is None:
        return {**result,'reason':'measurement_time_required'}
    if requirement.value.get('kind') != 'number' or candidate.value.get('kind') != 'number':
        return {**result,'reason':'numeric_comparison_required'}
    if requirement.value.get('unit') != candidate.value.get('unit'):
        return {**result,'reason':'different_canonical_unit'}
    try:
        threshold, value = Decimal(requirement.value['decimal']), Decimal(candidate.value['decimal'])
    except (InvalidOperation, KeyError, ValueError, TypeError):
        return {**result,'reason':'invalid_numeric_value'}
    if not threshold.is_finite() or not value.is_finite():
        return {**result,'reason':'invalid_numeric_value'}
    predicates = {'eq':lambda: value==threshold, 'gte':lambda: value>=threshold,
                  'lte':lambda: value<=threshold, 'gt':lambda: value>threshold, 'lt':lambda: value<threshold}
    if requirement.operator not in predicates or candidate.operator != 'eq':
        return {**result,'reason':'unsupported_comparison_operator'}
    return {**result,'status':'satisfied' if predicates[requirement.operator]() else 'not_satisfied',
            'reason':'explicit_numeric_requirement_comparison',
            'evidence':{'requirement':requirement.source,'candidate':candidate.source,
                        'subject_links':[{'requirement_subject':left,'candidate_subject':right}
                            for left,right in sorted(subject_links)
                            if left in requirement.subject_refs and right in candidate.subject_refs]}}
