"""Compatibility path; canonical implementation: teoria.domains.public_procurement.data_profile."""

from importlib import import_module as _import_module

_implementation = _import_module('teoria.domains.public_procurement.data_profile')
__all__ = [name for name in vars(_implementation) if not name.startswith('__')]
globals().update({name: getattr(_implementation, name) for name in __all__})

run_ontology_profile = _implementation.run_data_profile
