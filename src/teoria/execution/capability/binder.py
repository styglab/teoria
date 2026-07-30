from __future__ import annotations

from typing import Any, Iterator

from teoria.execution.mapping.codec import apply_codec
from teoria.models.capability import CapabilityDefinition, CapabilityInput, CapabilityStep
from teoria.registry.loader import RegistryCatalog


class CapabilityBindError(ValueError):
    pass


class CapabilityBinder:
    def bind(self, catalog: RegistryCatalog, capability: CapabilityDefinition, step: CapabilityStep, inputs: dict[str, Any]) -> dict[str, Any]:
        unknown = set(inputs) - set(capability.inputs)
        if unknown:
            raise CapabilityBindError(f"unknown capability inputs: {sorted(unknown)}")
        result: dict[str, Any] = {}
        for input_path, definition, value, indices in self._values(capability.inputs, inputs):
            reference, codec = self._request_binding(catalog, step.call, definition)
            if reference is None:
                continue
            encoded = apply_codec(codec, value)
            if encoded is None:
                continue
            prefix = f"{step.call}.request."
            self._set_path(result, reference[len(prefix):], encoded, indices)
        return result

    def _request_binding(self, catalog: RegistryCatalog, call: str, definition: CapabilityInput) -> tuple[str | None, str | None]:
        prefix = f"{call}.request."
        if definition.field:
            return definition.field, None
        if not definition.property:
            return None, None
        ontology_id, object_id, property_id = definition.property.split(".")
        matches = []
        for mapping in catalog.mappings.values():
            if mapping.ontology != ontology_id:
                continue
            for binding in mapping.bindings.get(f"{object_id}.{property_id}", []):
                if isinstance(binding.field, str) and binding.field.startswith(prefix):
                    matches.append((binding.field, binding.encode))
        if not matches:
            raise CapabilityBindError(f"no request binding for '{definition.property}' and '{call}'")
        if len(matches) > 1:
            raise CapabilityBindError(f"ambiguous request bindings for '{definition.property}' and '{call}'")
        return matches[0]

    def _values(
        self,
        definitions: dict[str, CapabilityInput],
        supplied: dict[str, Any],
        prefix: str = "",
        indices: tuple[int, ...] = (),
    ) -> Iterator[tuple[str, CapabilityInput, Any, tuple[int, ...]]]:
        if not isinstance(supplied, dict):
            raise CapabilityBindError(f"input '{prefix}' must be an object")
        unknown = set(supplied) - set(definitions)
        if unknown:
            raise CapabilityBindError(f"unknown fields in '{prefix or 'inputs'}': {sorted(unknown)}")
        for input_id, definition in definitions.items():
            path = f"{prefix}.{input_id}" if prefix else input_id
            if input_id not in supplied:
                if definition.required:
                    raise CapabilityBindError(f"required input '{path}' is missing")
                if definition.default is None:
                    continue
                value = definition.default
            else:
                value = supplied[input_id]
            if definition.fields:
                if definition.collection == "list":
                    if not isinstance(value, list):
                        raise CapabilityBindError(f"input '{path}' must be a list")
                    for index, item in enumerate(value):
                        yield from self._values(definition.fields, item, path, indices + (index,))
                else:
                    yield from self._values(definition.fields, value, path, indices)
            else:
                if definition.collection == "list" and not isinstance(value, list):
                    raise CapabilityBindError(f"input '{path}' must be a list")
                yield path, definition, value, indices

    @staticmethod
    def _set_path(result: dict[str, Any], path: str, value: Any, indices: tuple[int, ...]) -> None:
        current: Any = result
        index_cursor = 0
        segments = path.split(".")
        for position, raw_segment in enumerate(segments):
            is_array = raw_segment.endswith("[]")
            segment = raw_segment[:-2] if is_array else raw_segment
            last = position == len(segments) - 1
            if is_array:
                if index_cursor >= len(indices):
                    raise CapabilityBindError(f"array field '{path}' requires a composite list input")
                item_index = indices[index_cursor]
                index_cursor += 1
                array = current.setdefault(segment, [])
                while len(array) <= item_index:
                    array.append({})
                if last:
                    array[item_index] = value
                else:
                    current = array[item_index]
            elif last:
                current[segment] = value
            else:
                current = current.setdefault(segment, {})
