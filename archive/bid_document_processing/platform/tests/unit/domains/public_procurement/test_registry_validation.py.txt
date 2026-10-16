from pathlib import Path

from teoria.domains.public_procurement.bid_eligibility.registry_validation import validate_eligibility_rules
from teoria.registry.composition import create_registry_validator
from teoria.registry.loader import RegistryLoader


REGISTRIES = Path(__file__).parents[4] / 'registries'


def test_default_validation_keeps_unsupported_evaluator_and_fact_diagnostics():
    catalog = RegistryLoader(REGISTRIES).load()
    rule_id, rule = next(iter(catalog.eligibility_rules.items()))
    catalog.eligibility_rules[rule_id] = rule.model_copy(update={
        'evaluator': 'unsupported_evaluator',
        'required_facts': ['public_procurement.bid_notice.missing_property'],
    })
    diagnostics = create_registry_validator().validate(catalog)
    assert {'unknown_rule_evaluator', 'unknown_rule_fact'} <= {d.code for d in diagnostics}
    assert all(d.path == catalog.eligibility_rule_paths[rule_id] for d in diagnostics)


def test_domain_validation_preserves_argument_types_and_uniqueness():
    catalog = RegistryLoader(REGISTRIES).load()
    rule_id, rule = next((key, value) for key, value in catalog.eligibility_rules.items() if value.arguments)
    argument = rule.arguments[0].model_copy(update={'data_type': 'unknown_type'})
    catalog.eligibility_rules[rule_id] = rule.model_copy(update={'arguments': [argument, argument]})
    diagnostics = validate_eligibility_rules(catalog)
    assert {'duplicate_rule_argument', 'unknown_data_type'} <= {d.code for d in diagnostics}
