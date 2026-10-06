from __future__ import annotations

import types
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog
from teoria.registry.validation.duplicates import check_duplicates

BUILTIN_DATA_TYPES = {"string", "integer", "number", "boolean"}
RUNTIME_CONTRACT_BUILTIN_DATA_TYPES = BUILTIN_DATA_TYPES | {"date", "datetime"}


class FieldValidationMixin:
    def _source_field_category(self, reference: str, catalog: RegistryCatalog) -> str | None:
        parts = reference.split(".")
        if len(parts) < 3 or parts[0] not in catalog.sources:
            return None
        source = catalog.sources[parts[0]]
        if source.source.type == "database":
            relation = next((item for item in source.source.relations if item.id == parts[1]), None)
            if relation is None:
                return None
            fields = relation.fields
            field = None
            for index, field_id in enumerate(parts[2:]):
                field = next((item for item in fields if item.id == field_id), None)
                if field is None:
                    return None
                if index < len(parts[2:]) - 1:
                    fields = field.fields
            if field is None:
                return None
            if field.data_type:
                definition = catalog.data_types.get(field.data_type)
                return definition.base_type if definition else field.data_type
            return field.type or ("object" if field.ref else None)
        if len(parts) < 4:
            return None
        operation = next((item for item in source.source.operations if item.id == parts[1]), None)
        if operation is None:
            return None
        objects = {item.id: item for item in source.source.components.objects}
        if parts[2] == "response":
            fields = objects[operation.response.data.ref].fields if operation.response.data.ref else operation.response.data.fields
            field_parts = parts[3:]
        elif parts[2] == "request" and operation.request and len(parts) >= 5:
            container = getattr(operation.request, parts[3], None)
            fields = container.fields if container else []
            field_parts = parts[4:]
        else:
            return None
        field = None
        for index, raw_id in enumerate(field_parts):
            field_id = raw_id[:-2] if raw_id.endswith("[]") else raw_id
            field = next((item for item in fields if item.id == field_id), None)
            if field is None:
                return None
            if index < len(field_parts) - 1:
                if field.ref in objects:
                    fields = objects[field.ref].fields
                elif field.items and field.items.ref in objects:
                    fields = objects[field.items.ref].fields
                else:
                    fields = field.fields
        if field and field.type == "array" and field.items:
            field = field.items
        if field is None:
            return None
        if field.data_type:
            definition = catalog.data_types.get(field.data_type)
            return definition.base_type if definition else field.data_type
        return field.type or ("object" if field.ref else None)

    @staticmethod
    def _ontology_property_category(prop: Any, catalog: RegistryCatalog) -> str:
        if prop.value_set:
            category = "string"
        else:
            definition = catalog.data_types.get(prop.data_type)
            category = definition.base_type if definition else prop.data_type
        return f"list:{category}" if prop.collection == "list" else category

    @classmethod
    def _annotation_categories(cls, annotation: Any) -> set[str]:
        if annotation is None:
            return set()
        origin = get_origin(annotation)
        if origin in {Union, types.UnionType}:
            categories: set[str] = set()
            for item in get_args(annotation):
                if item is not type(None):
                    categories.update(cls._annotation_categories(item))
            return categories
        if origin is list:
            inner = cls._annotation_categories(get_args(annotation)[0])
            return {f"list:{item}" for item in inner}
        category = {
            str: "string", int: "integer", float: "number", Decimal: "number",
            bool: "boolean", date: "date", datetime: "datetime", dict: "object", Any: "any",
        }.get(annotation)
        return {category} if category else set()

    @staticmethod
    def _categories_compatible(actual: str, expected: str) -> bool:
        if "any" in {actual, expected} or actual == expected:
            return True
        return (actual, expected) == ("integer", "number")

    @staticmethod
    def _check_duplicates(values: list[str], kind: str, path: Path, diagnostics: list[Diagnostic], location: str | None = None) -> None:
        check_duplicates(values, kind, path, diagnostics, location)

    @classmethod
    def _check_required(cls, fields: list, required: list[str], path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        cls._check_duplicates(required, "required_field", path, diagnostics, location)
        field_ids = {field.id for field in fields}
        for field_id in required:
            if field_id not in field_ids:
                diagnostics.append(Diagnostic("unknown_required_field", f"required field '{field_id}' is not declared in fields", path, location=location))

    def _validate_fields(
        self, fields: list, objects: dict, catalog: RegistryCatalog, path: Path,
        location: str, diagnostics: list[Diagnostic], *, require_id: bool,
        allowed_builtin_types: set[str] = BUILTIN_DATA_TYPES,
    ) -> None:
        ids = [field.id for field in fields if field.id is not None]
        self._check_duplicates(ids, "field", path, diagnostics, location)
        for index, field in enumerate(fields):
            field_location = f"{location}.{field.id or index}"
            if require_id and not field.id:
                diagnostics.append(Diagnostic("missing_field_id", "field id is required", path, location=field_location))
            if field.ref and field.ref not in objects:
                diagnostics.append(Diagnostic("unknown_ref", f"unknown local object ref '{field.ref}'", path, location=field_location))
            declared_data_type = field.data_type
            resolved_data_type = declared_data_type
            if declared_data_type and declared_data_type not in allowed_builtin_types:
                definition = catalog.data_types.get(declared_data_type)
                if not definition:
                    diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{declared_data_type}'", path, location=field_location))
                    resolved_data_type = None
                else:
                    resolved_data_type = definition.base_type
            if field.default is not None:
                self._check_value_type(field.default, resolved_data_type, "default_type_mismatch", path, field_location, diagnostics)
                allowed_values = {value.value for value in field.values}
                if allowed_values and str(field.default) not in allowed_values:
                    diagnostics.append(Diagnostic("default_not_in_values", f"default '{field.default}' is not one of the declared values", path, location=field_location))
            self._check_duplicates([value.value for value in field.values], "value", path, diagnostics, field_location)
            if field.fields:
                self._check_required(field.fields, field.required, path, field_location, diagnostics)
                self._validate_fields(field.fields, objects, catalog, path, f"{field_location}.fields", diagnostics, require_id=True, allowed_builtin_types=allowed_builtin_types)
            elif field.required:
                referenced_fields = objects[field.ref].fields if field.ref in objects else []
                self._check_required(referenced_fields, field.required, path, field_location, diagnostics)
            if field.items:
                self._validate_fields([field.items], objects, catalog, path, f"{field_location}.items", diagnostics, require_id=False, allowed_builtin_types=allowed_builtin_types)

    @staticmethod
    def _check_value_type(value: Any, declared_type: str | None, code: str, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        matches = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
        }
        if declared_type in matches and not matches[declared_type](value):
            diagnostics.append(Diagnostic(code, f"value {value!r} does not match type '{declared_type}'", path, location=location))
