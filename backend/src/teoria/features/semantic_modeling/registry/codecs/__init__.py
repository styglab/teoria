"""Resolve pure Mapping codecs shared by contract validation and runtime execution."""

from importlib import import_module


# Preserve the codec IDs serialized into immutable historical Registry artifacts.
_MODULES = {
    "common": "teoria.features.semantic_modeling.registry.codecs.primitives",
    "company": "teoria.features.semantic_modeling.registry.codecs.legacy.company",
    "tax": "teoria.features.semantic_modeling.registry.codecs.legacy.tax",
}


def resolve_codec(reference: str):
    module, name = reference.rsplit(".", 1)
    if module not in _MODULES:
        raise ImportError(f"Unknown mapping codec module: {module}")
    return getattr(import_module(_MODULES[module]), name)
