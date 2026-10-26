from teoria.features.semantic_modeling.registry.codecs import resolve_codec
from typing import Any


def apply_codec(reference: str | None, value: Any) -> Any:
    if reference is None:
        return value
    function = resolve_codec(reference)
    if isinstance(value, dict):
        return function(**value)
    return function(value)
