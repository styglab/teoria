import re
from pathlib import Path
from typing import Any, Mapping

from teoria_provider.diagnostics import Diagnostic
from teoria_provider.schema import ProviderDefinition

RECORD_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$")
BUILTIN_DATA_TYPES = {"string", "integer", "number", "boolean"}


class ProviderContractValidator:
    def validate(self, definition: ProviderDefinition, *, data_types: Mapping[str, Any] | None = None,
                 path: Path | None = None, root: str = "provider",
                 allow_unknown_data_types: bool = False) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        types = data_types or {}
        contract_path = path or Path("<provider-contract>")
        objects = {obj.id: obj for obj in definition.components.objects}
        self._duplicates([obj.id for obj in definition.components.objects], "object", contract_path, diagnostics)
        self._duplicates([operation.id for operation in definition.operations], "operation", contract_path, diagnostics)
        self._duplicates([f"{operation.method} {operation.path}" for operation in definition.operations], "endpoint", contract_path, diagnostics)
        for obj in definition.components.objects:
            self._fields(obj.fields, objects, types, contract_path, f"{root}.components.objects.{obj.id}.fields", diagnostics, True, allow_unknown_data_types)
        self._circular_refs(objects, contract_path, diagnostics, root)
        for operation in definition.operations:
            response = operation.response
            if response.data.ref and response.data.ref not in objects:
                diagnostics.append(Diagnostic("unknown_ref", f"unknown local object ref '{response.data.ref}'", contract_path, location=operation.id))
            if response.data.record_path != "." and not RECORD_PATH_PATTERN.fullmatch(response.data.record_path):
                diagnostics.append(Diagnostic("invalid_record_path", f"invalid record path '{response.data.record_path}'", contract_path, location=f"{operation.id}.response.data.record_path"))
            self._content_type(operation.request.content_type if operation.request else None, contract_path, f"{operation.id}.request.content_type", diagnostics)
            self._content_type(response.content_type, contract_path, f"{operation.id}.response.content_type", diagnostics)
            if operation.request and operation.request.body and not operation.request.content_type:
                diagnostics.append(Diagnostic("missing_request_content_type", "request content_type is required when body is declared", contract_path, location=f"{operation.id}.request"))
            self._duplicates([str(error.http_status) for error in operation.errors], "error_status", contract_path, diagnostics, f"{operation.id}.errors")
            if operation.request:
                for section_name in ("query", "header", "body"):
                    container = getattr(operation.request, section_name)
                    if container:
                        location = f"{operation.id}.request.{section_name}"
                        self._required(container.fields, container.required, contract_path, location, diagnostics)
                        self._fields(container.fields, objects, types, contract_path, f"{location}.fields", diagnostics, True, allow_unknown_data_types)
            if response.control:
                control = response.control
                if control.record_path != "." and not RECORD_PATH_PATTERN.fullmatch(control.record_path):
                    diagnostics.append(Diagnostic("invalid_record_path", f"invalid control record path '{control.record_path}'", contract_path, location=f"{operation.id}.response.control.record_path"))
                if control.success.field not in {field.id for field in control.fields}:
                    diagnostics.append(Diagnostic("unknown_control_success_field", f"unknown control success field '{control.success.field}'", contract_path, location=f"{operation.id}.response.control.success"))
                self._fields(control.fields, objects, types, contract_path, f"{operation.id}.response.control.fields", diagnostics, True, allow_unknown_data_types)
            if response.data.fields:
                self._fields(response.data.fields, objects, types, contract_path, f"{operation.id}.response.data.fields", diagnostics, True, allow_unknown_data_types)
        return diagnostics

    def _fields(self, fields: list, objects: dict, data_types: Mapping[str, Any], path: Path,
                location: str, diagnostics: list[Diagnostic], require_id: bool,
                allow_unknown_data_types: bool = False) -> None:
        self._duplicates([field.id for field in fields if field.id], "field", path, diagnostics, location)
        for index, field in enumerate(fields):
            current = f"{location}.{field.id or index}"
            if require_id and not field.id:
                diagnostics.append(Diagnostic("missing_field_id", "field id is required", path, location=current))
            if field.ref and field.ref not in objects:
                diagnostics.append(Diagnostic("unknown_ref", f"unknown local object ref '{field.ref}'", path, location=current))
            resolved = field.data_type
            if resolved and resolved not in BUILTIN_DATA_TYPES:
                definition = data_types.get(resolved)
                if definition is None and not allow_unknown_data_types:
                    diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{resolved}'", path, location=current))
                    resolved = None
                elif definition is not None:
                    resolved = definition.base_type
            if field.default is not None:
                self._value_type(field.default, resolved, path, current, diagnostics)
                if field.values and str(field.default) not in {item.value for item in field.values}:
                    diagnostics.append(Diagnostic("default_not_in_values", f"default '{field.default}' is not one of the declared values", path, location=current))
            self._duplicates([item.value for item in field.values], "value", path, diagnostics, current)
            if field.fields:
                self._required(field.fields, field.required, path, current, diagnostics)
                self._fields(field.fields, objects, data_types, path, f"{current}.fields", diagnostics, True, allow_unknown_data_types)
            elif field.required:
                self._required(objects[field.ref].fields if field.ref in objects else [], field.required, path, current, diagnostics)
            if field.items:
                self._fields([field.items], objects, data_types, path, f"{current}.items", diagnostics, False, allow_unknown_data_types)

    @staticmethod
    def _duplicates(values: list[str], kind: str, path: Path, diagnostics: list[Diagnostic], location: str | None = None) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                diagnostics.append(Diagnostic(f"duplicate_{kind}", f"duplicate {kind} '{value}'", path, location=location))
            seen.add(value)

    @classmethod
    def _required(cls, fields: list, required: list[str], path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        cls._duplicates(required, "required_field", path, diagnostics, location)
        known = {field.id for field in fields}
        for field_id in required:
            if field_id not in known:
                diagnostics.append(Diagnostic("unknown_required_field", f"required field '{field_id}' is not declared in fields", path, location=location))

    @staticmethod
    def _value_type(value: Any, declared_type: str | None, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        checks = {"string": lambda item: isinstance(item, str),
                  "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
                  "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
                  "boolean": lambda item: isinstance(item, bool)}
        if declared_type in checks and not checks[declared_type](value):
            diagnostics.append(Diagnostic("default_type_mismatch", f"value {value!r} does not match type '{declared_type}'", path, location=location))

    @staticmethod
    def _content_type(value: str | None, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        if value is not None and "/" not in value:
            diagnostics.append(Diagnostic("invalid_content_type", f"invalid content type '{value}'", path, location=location))

    @staticmethod
    def _circular_refs(objects: dict, path: Path, diagnostics: list[Diagnostic], root: str) -> None:
        def refs_in(fields: list) -> set[str]:
            refs: set[str] = set()
            for field in fields:
                if field.ref:
                    refs.add(field.ref)
                refs.update(refs_in(field.fields))
                if field.items:
                    refs.update(refs_in([field.items]))
            return refs
        graph = {key: refs_in(value.fields) & objects.keys() for key, value in objects.items()}
        visited: set[str] = set()
        active: list[str] = []
        def visit(object_id: str) -> None:
            if object_id in active:
                cycle = active[active.index(object_id):] + [object_id]
                diagnostics.append(Diagnostic("circular_ref", f"circular object reference: {' -> '.join(cycle)}", path, location=f"{root}.components.objects.{object_id}"))
                return
            if object_id in visited:
                return
            active.append(object_id)
            for target in graph[object_id]:
                visit(target)
            active.pop()
            visited.add(object_id)
        for object_id in graph:
            visit(object_id)
