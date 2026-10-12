"""Compatibility path; canonical implementation: teoria.admin.property_context_api."""

from importlib import import_module as _import_module

_implementation = _import_module('teoria.admin.property_context_api')
__all__ = [name for name in vars(_implementation) if not name.startswith('__')]
globals().update({name: getattr(_implementation, name) for name in __all__})

create_semantic_router = _implementation.create_property_context_router
