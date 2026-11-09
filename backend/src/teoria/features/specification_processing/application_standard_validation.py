"""Describe executable rules separately from source-only extraction proposals."""
from teoria.features.goods_normalization.contracts import NormalizationPackage
from teoria.features.specification_processing.models import StandardArtifact


def application_standard_readiness(body: dict) -> dict:
    if body.get('artifact_kind') == 'goods_normalization_package':
        package = NormalizationPackage.model_validate(body)
        definition_count = len(package.concepts)
        rule_count = len(package.profile.entities) + len(package.profile.requirements) + len(package.profile.relations)
        kind = 'ontology_profile'
        classification = package.profile.classification_code
    else:
        standard = StandardArtifact.model_validate(body)
        definition_count = len(standard.definitions)
        rule_count = sum(len(binding.properties) for binding in standard.bindings)
        kind = 'extraction_draft'
        classification = standard.classification_code
    ready = definition_count > 0 and rule_count > 0
    return {'ready': ready, 'reason': None if ready else 'standard_has_no_application_rules',
            'definition_count': definition_count, 'rule_count': rule_count,
            'standard_kind': kind, 'classification_code': classification}


def require_application_rules(body: dict) -> dict:
    readiness = application_standard_readiness(body)
    if not readiness['ready']:
        raise ValueError(readiness['reason'])
    return readiness
