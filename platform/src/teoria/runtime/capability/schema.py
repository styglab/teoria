from __future__ import annotations

from datetime import date, datetime
from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.registry.schema.capability import CapabilityDefinition, CapabilityInput
from teoria.registry.schema.ontology import OntologyProperty


BUILTIN_TYPES: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
}


def capability_input_schema(catalog: RegistryCatalog, capability: CapabilityDefinition) -> dict[str, Any]:
    properties = {key: _input_schema(catalog, value) for key, value in capability.inputs.items()}
    required = [key for key, value in capability.inputs.items() if value.required]
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def coerce_capability_inputs(
    catalog: RegistryCatalog,
    capability: CapabilityDefinition,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: _coerce_input(catalog, definition, arguments[key])
        for key, definition in capability.inputs.items()
        if key in arguments
    }


def _input_schema(catalog: RegistryCatalog, definition: CapabilityInput) -> dict[str, Any]:
    if definition.fields:
        properties = {key: _input_schema(catalog, value) for key, value in definition.fields.items()}
        schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
        required = [key for key, value in definition.fields.items() if value.required]
        if required:
            schema["required"] = required
    else:
        property_definition = _resolve_property(catalog, definition.property) if definition.property else None
        type_id = _effective_type(property_definition, definition)
        schema = _type_schema(catalog, type_id, property_definition)
    if definition.collection == "list":
        schema = {"type": "array", "items": schema}
    if definition.default is not None:
        schema["default"] = definition.default
    if definition.enum is not None:
        schema["enum"] = definition.enum
    if definition.minimum is not None:
        schema["minimum"] = definition.minimum
    if definition.maximum is not None:
        schema["maximum"] = definition.maximum
    return schema


def _type_schema(
    catalog: RegistryCatalog,
    type_id: str,
    property_definition: OntologyProperty | None,
) -> dict[str, Any]:
    description = property_definition.description if property_definition else None
    if property_definition and property_definition.value_set:
        schema: dict[str, Any] = {
            "type": "string",
            "enum": [item.id for item in catalog.value_sets[property_definition.value_set].values],
        }
    elif type_id in BUILTIN_TYPES:
        schema = dict(BUILTIN_TYPES[type_id])
    else:
        data_type = catalog.data_types[type_id]
        schema = dict(BUILTIN_TYPES[data_type.base_type])
        if data_type.pattern:
            schema["pattern"] = data_type.pattern
    if description:
        schema["description"] = description
    return schema


def _coerce_input(catalog: RegistryCatalog, definition: CapabilityInput, value: Any) -> Any:
    if definition.collection == "list":
        scalar = definition.model_copy(update={"collection": "scalar"})
        return [_coerce_input(catalog, scalar, item) for item in value]
    if definition.fields:
        return {
            key: _coerce_input(catalog, child, value[key])
            for key, child in definition.fields.items()
            if key in value
        }
    property_definition = _resolve_property(catalog, definition.property) if definition.property else None
    type_id = _effective_type(property_definition, definition)
    if type_id == "date" and isinstance(value, str):
        return date.fromisoformat(value)
    if type_id == "datetime" and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _effective_type(property_definition: OntologyProperty | None, definition: CapabilityInput) -> str:
    if definition.data_type:
        return definition.data_type
    if property_definition and property_definition.value_set:
        return "string"
    assert property_definition and property_definition.data_type
    return property_definition.data_type


def _resolve_property(catalog: RegistryCatalog, reference: str | None) -> OntologyProperty:
    if not reference:
        raise ValueError("property reference is required")
    ontology_id, object_id, property_id = reference.split(".")
    object_type = next(item for item in catalog.ontologies[ontology_id].object_types if item.id == object_id)
    return next(item for item in object_type.properties if item.id == property_id)
