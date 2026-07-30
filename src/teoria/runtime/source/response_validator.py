import re
from pathlib import Path
from typing import Any

from teoria.runtime.source.response import ExecutionResponse
from teoria.registry.schema.common import FieldDefinition
from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog


class SourceResponseValidator:
    def validate(self, catalog: RegistryCatalog, source_id: str, operation_id: str, response: ExecutionResponse) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        registry = catalog.sources[source_id]
        operation = next(item for item in registry.source.operations if item.id == operation_id)
        path = catalog.source_paths[source_id]
        location = f"{operation_id}.response"
        if response.status_code != operation.response.http_status:
            diagnostics.append(Diagnostic("unexpected_http_status", f"expected HTTP {operation.response.http_status}, got {response.status_code}", path, location=location))
            return diagnostics
        if response.content_type and response.content_type != operation.response.content_type:
            diagnostics.append(Diagnostic("unexpected_content_type", f"expected '{operation.response.content_type}', got '{response.content_type}'", path, location=location))
        control = operation.response.control
        if control:
            try:
                control_value = self._resolve_record_path(response.body, control.record_path)
                actual = control_value[control.success.field]
                if str(actual) != control.success.equals:
                    diagnostics.append(Diagnostic("source_operation_failed", f"expected {control.success.field}={control.success.equals!r}, got {actual!r}", path, location=f"{location}.control"))
                    return diagnostics
            except (KeyError, TypeError) as exc:
                diagnostics.append(Diagnostic("response_control_not_found", str(exc), path, location=f"{location}.control"))
                return diagnostics
        try:
            records = self._resolve_record_path(response.body, operation.response.data.record_path)
        except (KeyError, TypeError) as exc:
            diagnostics.append(Diagnostic("record_path_not_found", str(exc), path, location=f"{location}.data.record_path"))
            return diagnostics
        fields = operation.response.data.fields
        if operation.response.data.ref:
            obj = next(item for item in registry.source.components.objects if item.id == operation.response.data.ref)
            fields = obj.fields
        values = records if isinstance(records, list) else [records]
        for index, value in enumerate(values):
            self._validate_object(value, fields, registry, catalog, path, f"{location}.data[{index}]", diagnostics)
        return diagnostics

    @staticmethod
    def _resolve_record_path(body: Any, record_path: str) -> Any:
        if record_path == ".":
            return body
        current = body
        for segment in record_path.split("."):
            is_array = segment.endswith("[]")
            key = segment[:-2] if is_array else segment
            if not isinstance(current, dict) or key not in current:
                raise KeyError(f"record path segment '{key}' was not found")
            current = current[key]
            if is_array and not isinstance(current, list):
                raise TypeError(f"record path segment '{key}' must be an array")
        return current

    def _validate_object(self, value: Any, fields: list[FieldDefinition], registry: Any, catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("response_type_mismatch", "expected object record", path, location=location))
            return
        for field in fields:
            if not field.id or field.id not in value:
                continue
            item = value[field.id]
            field_location = f"{location}.{field.id}"
            if field.ref:
                obj = next((candidate for candidate in registry.source.components.objects if candidate.id == field.ref), None)
                self._validate_object(item, obj.fields if obj else [], registry, catalog, path, field_location, diagnostics)
                continue
            if field.type == "object":
                self._validate_object(item, field.fields, registry, catalog, path, field_location, diagnostics)
                continue
            if field.type == "array":
                if not isinstance(item, list):
                    diagnostics.append(Diagnostic("response_type_mismatch", "expected array", path, location=field_location))
                    continue
                if field.max_items is not None and len(item) > field.max_items:
                    diagnostics.append(Diagnostic("response_max_items_exceeded", f"maximum {field.max_items} items are allowed", path, location=field_location))
                if field.items:
                    for index, child in enumerate(item):
                        self._validate_field(child, field.items, registry, catalog, path, f"{field_location}[{index}]", diagnostics)
                continue
            self._validate_scalar(item, field, catalog, path, field_location, diagnostics)

    def _validate_field(self, item: Any, field: FieldDefinition, registry: Any, catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        if field.ref:
            obj = next((candidate for candidate in registry.source.components.objects if candidate.id == field.ref), None)
            self._validate_object(item, obj.fields if obj else [], registry, catalog, path, location, diagnostics)
        elif field.type == "object":
            self._validate_object(item, field.fields, registry, catalog, path, location, diagnostics)
        elif field.type == "array":
            if not isinstance(item, list):
                diagnostics.append(Diagnostic("response_type_mismatch", "expected array", path, location=location))
            elif field.items:
                for index, child in enumerate(item):
                    self._validate_field(child, field.items, registry, catalog, path, f"{location}[{index}]", diagnostics)
        else:
            self._validate_scalar(item, field, catalog, path, location, diagnostics)

    @staticmethod
    def _validate_scalar(item: Any, field: FieldDefinition, catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        data_type = field.data_type
        definition = catalog.data_types.get(data_type) if data_type else None
        base_type = definition.base_type if definition else data_type
        expected = {
            "string": lambda candidate: isinstance(candidate, str),
            "integer": lambda candidate: isinstance(candidate, int) and not isinstance(candidate, bool),
            "number": lambda candidate: isinstance(candidate, (int, float)) and not isinstance(candidate, bool),
            "boolean": lambda candidate: isinstance(candidate, bool),
        }
        if base_type in expected and not expected[base_type](item):
            diagnostics.append(Diagnostic("response_type_mismatch", f"expected {base_type}", path, location=location))
            return
        # Source APIs commonly encode an absent optional scalar as an empty
        # string. Preserve that wire value, but do not apply enum/data-type
        # constraints intended for a present value.
        if item == "":
            return
        allowed = {entry.value for entry in field.values}
        if allowed and str(item) not in allowed:
            diagnostics.append(Diagnostic("response_value_not_allowed", f"value {item!r} is not declared", path, location=location))
        if definition and definition.pattern and isinstance(item, str):
            if not re.fullmatch(definition.pattern, item):
                diagnostics.append(Diagnostic("response_data_type_mismatch", f"value does not match data type '{field.data_type}'", path, location=location))
