from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from teoria_provider.diagnostics import Diagnostic
from teoria_provider.models import AuthenticationRequirement, PreparedRequest
from teoria_provider.schema import FieldContainer, FieldDefinition, ProviderDefinition


class RequestBuildError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(map(str, diagnostics)))


class ProviderRequestBuilder:
    def build(self, definition: ProviderDefinition, operation_id: str, input_data: dict[str, Any], *,
              data_types: Mapping[str, Any] | None = None, path: Path | None = None) -> PreparedRequest:
        diagnostics: list[Diagnostic] = []
        contract_path = path or Path("<provider-contract>")
        types = data_types or {}
        operation = next((item for item in definition.operations if item.id == operation_id), None)
        if operation is None:
            raise RequestBuildError([Diagnostic("unknown_operation", f"unknown operation '{operation_id}'", contract_path)])
        for section in input_data:
            if section not in {"query", "header", "body"}:
                diagnostics.append(Diagnostic("unknown_input_section", f"unknown input section '{section}'", contract_path, location=operation_id))
        request = operation.request
        query = self._build_container(request.query if request else None, input_data.get("query", {}), definition, types, contract_path, f"{operation_id}.request.query", diagnostics) or {}
        headers = self._build_container(request.header if request else None, input_data.get("header", {}), definition, types, contract_path, f"{operation_id}.request.header", diagnostics) or {}
        body = self._build_container(request.body if request else None, input_data.get("body", {}), definition, types, contract_path, f"{operation_id}.request.body", diagnostics)
        if diagnostics:
            raise RequestBuildError(diagnostics)
        if request and request.content_type:
            headers.setdefault("Content-Type", request.content_type)
        authentication = definition.access.authentication
        requirement = None
        if authentication and authentication.type != "none" and authentication.location and authentication.name and authentication.credential_env:
            requirement = AuthenticationRequirement(type=authentication.type, location=authentication.location,
                name=authentication.name, environment_variable=authentication.credential_env)
        return PreparedRequest(source_id=definition.id, operation_id=operation_id, method=operation.method,
            url=f"{definition.access.base_url}{operation.path}", query=query,
            headers={key: str(value) for key, value in headers.items()},
            body=body if request and request.body else None, authentication=requirement,
            idempotent=operation.idempotent or operation.method in {"GET", "HEAD", "OPTIONS"})

    def _build_container(self, container: FieldContainer | None, supplied: Any, definition: ProviderDefinition,
                         data_types: Mapping[str, Any], path: Path, location: str,
                         diagnostics: list[Diagnostic]) -> dict[str, Any] | None:
        if container is None:
            if supplied:
                diagnostics.append(Diagnostic("undeclared_input_section", "input was supplied for an undeclared section", path, location=location))
            return None
        if not isinstance(supplied, dict):
            diagnostics.append(Diagnostic("invalid_input_type", "input section must be an object", path, location=location))
            return {}
        fields = {field.id: field for field in container.fields if field.id}
        result: dict[str, Any] = {}
        for field_id in supplied:
            if field_id not in fields:
                diagnostics.append(Diagnostic("unknown_input_field", f"unknown input field '{field_id}'", path, location=location))
        for field_id, field in fields.items():
            if field_id in supplied:
                if field_id in container.required and supplied[field_id] == "":
                    diagnostics.append(Diagnostic("empty_required_input", f"required input '{field_id}' cannot be empty", path, location=location))
                result[field_id] = self._validate_value(supplied[field_id], field, definition, data_types, path,
                    f"{location}.{field_id}", diagnostics, allow_empty=field_id not in container.required)
            elif field.default is not None:
                result[field_id] = field.default
            elif field_id in container.required:
                diagnostics.append(Diagnostic("missing_required_input", f"required input '{field_id}' is missing", path, location=location))
        return result

    def _validate_value(self, value: Any, field: FieldDefinition, definition: ProviderDefinition,
                        data_types: Mapping[str, Any], path: Path, location: str,
                        diagnostics: list[Diagnostic], *, allow_empty: bool = False) -> Any:
        if value == "" and allow_empty:
            return value
        if field.ref:
            obj = next((item for item in definition.components.objects if item.id == field.ref), None)
            return self._validate_object(value, obj.fields if obj else [], field.required, definition, data_types, path, location, diagnostics)
        if field.type == "array":
            if not isinstance(value, list):
                diagnostics.append(Diagnostic("input_type_mismatch", "expected array", path, location=location))
                return value
            if field.max_items is not None and len(value) > field.max_items:
                diagnostics.append(Diagnostic("max_items_exceeded", f"maximum {field.max_items} items are allowed", path, location=location))
            return [self._validate_value(item, field.items, definition, data_types, path, f"{location}[{index}]", diagnostics)
                    for index, item in enumerate(value)] if field.items else value
        if field.type == "object":
            return self._validate_object(value, field.fields, field.required, definition, data_types, path, location, diagnostics)
        declared = data_types.get(field.data_type) if field.data_type else None
        base_type = getattr(declared, "base_type", None) or field.data_type
        expected = {"string": lambda item: isinstance(item, str),
                    "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
                    "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
                    "boolean": lambda item: isinstance(item, bool)}
        if base_type in expected and not expected[base_type](value):
            diagnostics.append(Diagnostic("input_type_mismatch", f"expected {base_type}", path, location=location))
            return value
        allowed = {item.value for item in field.values}
        if allowed and str(value) not in allowed:
            diagnostics.append(Diagnostic("input_value_not_allowed", f"value {value!r} is not allowed", path, location=location))
        pattern = getattr(declared, "pattern", None)
        if pattern and isinstance(value, str) and not re.fullmatch(pattern, value):
            diagnostics.append(Diagnostic("input_data_type_mismatch", f"value does not match data type '{field.data_type}'", path, location=location))
        return value

    def _validate_object(self, value: Any, fields: list[FieldDefinition], required: list[str],
                         definition: ProviderDefinition, data_types: Mapping[str, Any], path: Path,
                         location: str, diagnostics: list[Diagnostic]) -> Any:
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("input_type_mismatch", "expected object", path, location=location))
            return value
        declared = {field.id: field for field in fields if field.id}
        result: dict[str, Any] = {}
        for key in value:
            if key not in declared:
                diagnostics.append(Diagnostic("unknown_input_field", f"unknown input field '{key}'", path, location=location))
        for field_id, field in declared.items():
            if field_id in value:
                if field_id in required and value[field_id] == "":
                    diagnostics.append(Diagnostic("empty_required_input", f"required input '{field_id}' cannot be empty", path, location=location))
                result[field_id] = self._validate_value(value[field_id], field, definition, data_types, path,
                    f"{location}.{field_id}", diagnostics, allow_empty=field_id not in required)
            elif field.default is not None:
                result[field_id] = field.default
            elif field_id in required:
                diagnostics.append(Diagnostic("missing_required_input", f"required input '{field_id}' is missing", path, location=location))
        return result
