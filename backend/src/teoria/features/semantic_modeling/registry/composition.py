"""Assemble generic Registry validation with the installed domain contracts."""

from teoria.features.semantic_modeling.registry.validation.registry import RegistryValidator


def create_registry_validator() -> RegistryValidator:
    return RegistryValidator()
