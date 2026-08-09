import re
from pathlib import Path
from typing import Any, Mapping

from teoria_provider.diagnostics import Diagnostic
from teoria_provider.models import ExecutionResponse
from teoria_provider.schema import FieldDefinition, ProviderDefinition


class ProviderResponseValidator:
    def validate(self, definition: ProviderDefinition, operation_id: str, response: ExecutionResponse, *,
                 data_types: Mapping[str, Any] | None = None, path: Path | None = None) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        contract_path = path or Path("<provider-contract>")
        types = data_types or {}
        operation = next(item for item in definition.operations if item.id == operation_id)
        location = f"{operation_id}.response"
        if response.status_code != operation.response.http_status:
            return [Diagnostic("unexpected_http_status", f"expected HTTP {operation.response.http_status}, got {response.status_code}", contract_path, location=location)]
        if response.content_type and response.content_type != operation.response.content_type:
            diagnostics.append(Diagnostic("unexpected_content_type", f"expected '{operation.response.content_type}', got '{response.content_type}'", contract_path, location=location))
        control = operation.response.control
        if control:
            try:
                actual = self._resolve_record_path(response.body, control.record_path)[control.success.field]
                if str(actual) != control.success.equals:
                    diagnostics.append(Diagnostic("source_operation_failed", f"expected {control.success.field}={control.success.equals!r}, got {actual!r}", contract_path, location=f"{location}.control"))
                    return diagnostics
            except (KeyError, TypeError) as exc:
                diagnostics.append(Diagnostic("response_control_not_found", str(exc), contract_path, location=f"{location}.control"))
                return diagnostics
        try:
            records = self._resolve_record_path(response.body, operation.response.data.record_path)
        except (KeyError, TypeError) as exc:
            # Several public APIs omit the collection node entirely for an empty
            # page. Pagination's total count is the authoritative empty signal;
            # a missing record path remains an error for every non-empty response.
            is_empty_page = False
            if operation.pagination:
                try:
                    is_empty_page = int(self._resolve_record_path(
                        response.body, operation.pagination.total_count
                    )) == 0
                except (KeyError, TypeError, ValueError):
                    pass
            if not is_empty_page:
                diagnostics.append(Diagnostic("record_path_not_found", str(exc), contract_path, location=f"{location}.data.record_path"))
                return diagnostics
            records = []
        fields = operation.response.data.fields
        if operation.response.data.ref:
            fields = next(item for item in definition.components.objects if item.id == operation.response.data.ref).fields
        for index, value in enumerate(records if isinstance(records, list) else [records]):
            self._validate_object(value, fields, definition, types, contract_path, f"{location}.data[{index}]", diagnostics)
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
                current = [current]
        return current

    def _validate_object(self, value: Any, fields: list[FieldDefinition], definition: ProviderDefinition,
                         data_types: Mapping[str, Any], path: Path, location: str,
                         diagnostics: list[Diagnostic]) -> None:
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("response_type_mismatch", "expected object record", path, location=location))
            return
        for field in fields:
            if not field.id or field.id not in value:
                continue
            item, field_location = value[field.id], f"{location}.{field.id}"
            if field.ref:
                obj = next((candidate for candidate in definition.components.objects if candidate.id == field.ref), None)
                self._validate_object(item, obj.fields if obj else [], definition, data_types, path, field_location, diagnostics)
            elif field.type == "object":
                self._validate_object(item, field.fields, definition, data_types, path, field_location, diagnostics)
            elif field.type == "array":
                if not isinstance(item, list):
                    diagnostics.append(Diagnostic("response_type_mismatch", "expected array", path, location=field_location))
                elif field.max_items is not None and len(item) > field.max_items:
                    diagnostics.append(Diagnostic("response_max_items_exceeded", f"maximum {field.max_items} items are allowed", path, location=field_location))
                elif field.items:
                    for index, child in enumerate(item):
                        self._validate_field(child, field.items, definition, data_types, path, f"{field_location}[{index}]", diagnostics)
            else:
                self._validate_scalar(item, field, data_types, path, field_location, diagnostics)

    def _validate_field(self, item: Any, field: FieldDefinition, definition: ProviderDefinition,
                        data_types: Mapping[str, Any], path: Path, location: str,
                        diagnostics: list[Diagnostic]) -> None:
        if field.ref:
            obj = next((candidate for candidate in definition.components.objects if candidate.id == field.ref), None)
            self._validate_object(item, obj.fields if obj else [], definition, data_types, path, location, diagnostics)
        elif field.type == "object":
            self._validate_object(item, field.fields, definition, data_types, path, location, diagnostics)
        elif field.type == "array":
            if not isinstance(item, list):
                diagnostics.append(Diagnostic("response_type_mismatch", "expected array", path, location=location))
            elif field.items:
                for index, child in enumerate(item):
                    self._validate_field(child, field.items, definition, data_types, path, f"{location}[{index}]", diagnostics)
        else:
            self._validate_scalar(item, field, data_types, path, location, diagnostics)

    @staticmethod
    def _validate_scalar(item: Any, field: FieldDefinition, data_types: Mapping[str, Any], path: Path,
                         location: str, diagnostics: list[Diagnostic]) -> None:
        declared = data_types.get(field.data_type) if field.data_type else None
        base_type = getattr(declared, "base_type", None) or field.data_type
        expected = {"string": lambda value: isinstance(value, str),
                    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
                    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
                    "boolean": lambda value: isinstance(value, bool)}
        if base_type in expected and not expected[base_type](item):
            diagnostics.append(Diagnostic("response_type_mismatch", f"expected {base_type}", path, location=location))
            return
        if item == "":
            return
        allowed = {entry.value for entry in field.values}
        if allowed and str(item) not in allowed:
            diagnostics.append(Diagnostic("response_value_not_allowed", f"value {item!r} is not declared", path, location=location))
        pattern = getattr(declared, "pattern", None)
        if pattern and isinstance(item, str) and not re.fullmatch(pattern, item):
            diagnostics.append(Diagnostic("response_data_type_mismatch", f"value does not match data type '{field.data_type}'", path, location=location))
