from importlib import import_module
from typing import Any


def apply_codec(reference: str | None, value: Any) -> Any:
    if reference is None:
        return value
    module_name, function_name = reference.rsplit(".", 1)
    function = getattr(import_module(f"teoria.features.runtime.mapping.transforms.{module_name}"), function_name)
    if isinstance(value, dict):
        return function(**value)
    return function(value)
