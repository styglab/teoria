from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog
from teoria.registry.validation.fields import (
    FieldValidationMixin,
    RUNTIME_CONTRACT_BUILTIN_DATA_TYPES,
)

from .evaluators import EVALUATORS


def validate_eligibility_rules(catalog: RegistryCatalog) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    known_evaluators = EVALUATORS
    for rule_id, rule in catalog.eligibility_rules.items():
        path = catalog.eligibility_rule_paths[rule_id]
        if rule.evaluator not in known_evaluators:
            diagnostics.append(Diagnostic("unknown_rule_evaluator", f"unknown rule evaluator '{rule.evaluator}'", path, location=f"eligibility_rules.{rule_id}.evaluator"))
        FieldValidationMixin._check_duplicates([item.id for item in rule.arguments], "rule_argument", path, diagnostics, f"eligibility_rules.{rule_id}.arguments")
        for argument in rule.arguments:
            if argument.data_type not in RUNTIME_CONTRACT_BUILTIN_DATA_TYPES and argument.data_type not in catalog.data_types:
                diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{argument.data_type}'", path, location=f"eligibility_rules.{rule_id}.arguments.{argument.id}.data_type"))
        for index, reference in enumerate(rule.required_facts):
            parts = reference.split(".")
            ontology = catalog.runtime_contracts.get(parts[0]) if len(parts) == 3 else None
            obj = next((item for item in ontology.object_types if item.id == parts[1]), None) if ontology else None
            if obj is None or parts[2] not in {item.id for item in obj.properties}:
                diagnostics.append(Diagnostic("unknown_rule_fact", f"unknown ontology property '{reference}'", path, location=f"eligibility_rules.{rule_id}.required_facts.{index}"))

    return diagnostics
