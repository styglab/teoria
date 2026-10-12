"""Compatibility path; canonical implementation: teoria.runtime.mapping.transforms.tax."""

from importlib import import_module as _import_module

_implementation = _import_module('teoria.runtime.mapping.transforms.tax')
__all__ = [name for name in vars(_implementation) if not name.startswith('__')]
globals().update({name: getattr(_implementation, name) for name in __all__})
