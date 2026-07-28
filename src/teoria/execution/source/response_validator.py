import re
from pathlib import Path
from typing import Any

from teoria.execution.source.models import ExecutionResponse
from teoria.models.common import FieldDefinition
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
            self._validate_object(value, fields, catalog, path, f"{location}.data[{index}]", diagnostics)
        return diagnostics

    @staticmethod
    def _resolve_record_path(body: Any, record_path: str) -> Any:
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

    def _validate_object(self, value: Any, fields: list[FieldDefinition], catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        if not isinstance(value, dict):
            diagnostics.append(Diagnostic("response_type_mismatch", "expected object record", path, location=location))
            return
        for field in fields:
            if not field.id or field.id not in value:
                continue
            item = value[field.id]
            expected = {
                "string": lambda candidate: isinstance(candidate, str),
                "integer": lambda candidate: isinstance(candidate, int) and not isinstance(candidate, bool),
                "number": lambda candidate: isinstance(candidate, (int, float)) and not isinstance(candidate, bool),
                "boolean": lambda candidate: isinstance(candidate, bool),
                "array": lambda candidate: isinstance(candidate, list),
                "object": lambda candidate: isinstance(candidate, dict),
            }
            if field.type in expected and not expected[field.type](item):
                diagnostics.append(Diagnostic("response_type_mismatch", f"expected {field.type}", path, location=f"{location}.{field.id}"))
                continue
            # Source APIs commonly encode an absent optional scalar as an empty
            # string. Preserve that wire value, but do not apply enum/format
            # constraints intended for a present value.
            if item == "":
                continue
            allowed = {entry.value for entry in field.values}
            if allowed and str(item) not in allowed:
                diagnostics.append(Diagnostic("response_value_not_allowed", f"value {item!r} is not declared", path, location=f"{location}.{field.id}"))
            if field.format and isinstance(item, str):
                definition = catalog.formats.get(field.format)
                if definition and definition.pattern and not re.fullmatch(definition.pattern, item):
                    diagnostics.append(Diagnostic("response_format_mismatch", f"value does not match format '{field.format}'", path, location=f"{location}.{field.id}"))
