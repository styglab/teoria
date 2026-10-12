"""Compatibility path; canonical implementation: teoria.domains.public_procurement.identity_validation."""

from importlib import import_module as _import_module

_implementation = _import_module('teoria.domains.public_procurement.identity_validation')
__all__ = [name for name in vars(_implementation) if not name.startswith('__')]
globals().update({name: getattr(_implementation, name) for name in __all__})

validate_procurement_shadow = _implementation.validate_procurement_identity
