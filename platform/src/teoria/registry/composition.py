"""Assemble generic Registry validation with the installed domain contracts."""

from teoria.domains.public_procurement.bid_eligibility.registry_validation import (
    validate_eligibility_rules,
)
from teoria.registry.validation.registry import RegistryValidator


def create_registry_validator() -> RegistryValidator:
    return RegistryValidator(domain_validators=(validate_eligibility_rules,))
