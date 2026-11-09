"""Resolve and invoke Mapping codecs while preserving historical external IDs."""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Preserve the codec IDs serialized into immutable historical Registry artifacts.
_MODULES = {
    "common": "teoria.platform.ontology.contracts.codecs.primitives",
    "company": "teoria.platform.ontology.contracts.codecs.legacy.company",
    "tax": "teoria.platform.ontology.contracts.codecs.legacy.tax",
}


def resolve_codec(reference: str):
    module, name = reference.rsplit(".", 1)
    if module not in _MODULES:
        raise ImportError(f"Unknown mapping codec module: {module}")
    return getattr(import_module(_MODULES[module]), name)


def apply_codec(reference: str | None, value: Any) -> Any:
    if reference is None:
        return value
    function = resolve_codec(reference)
    if isinstance(value, dict):
        return function(**value)
    return function(value)
