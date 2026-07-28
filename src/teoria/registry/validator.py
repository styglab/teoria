import re
from pathlib import Path
from typing import Any

from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog

RECORD_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$")


class RegistryValidator:
    def validate(self, catalog: RegistryCatalog, source_id: str | None = None) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        registries = catalog.sources.items()
        if source_id is not None:
            registry = catalog.sources.get(source_id)
            if registry is None:
                return [Diagnostic("unknown_source", f"unknown source '{source_id}'", catalog.root / "source")]
            registries = [(source_id, registry)]
        for current_source_id, registry in registries:
            path = catalog.source_paths[current_source_id]
            source = registry.source
            object_ids = [obj.id for obj in source.components.objects]
            operation_ids = [operation.id for operation in source.operations]

            if path.stem != source.id:
                diagnostics.append(Diagnostic("source_filename_mismatch", f"filename must match source id '{source.id}.yaml'", path, location="source.id"))
            self._check_duplicates(object_ids, "object", path, diagnostics)
            self._check_duplicates(operation_ids, "operation", path, diagnostics)
            self._check_duplicates([f"{operation.method} {operation.path}" for operation in source.operations], "endpoint", path, diagnostics)

            objects = {obj.id: obj for obj in source.components.objects}
            for obj in source.components.objects:
                self._validate_fields(obj.fields, objects, catalog, path, f"source.components.objects.{obj.id}.fields", diagnostics, require_id=True)
            self._check_circular_refs(objects, path, diagnostics)

            for operation in source.operations:
                ref = operation.response.data.ref
                if ref and ref not in objects:
                    diagnostics.append(Diagnostic("unknown_ref", f"unknown local object ref '{ref}'", path, location=operation.id))
                if not RECORD_PATH_PATTERN.fullmatch(operation.response.data.record_path):
                    diagnostics.append(Diagnostic("invalid_record_path", f"invalid record path '{operation.response.data.record_path}'", path, location=f"{operation.id}.response.data.record_path"))
                self._check_content_type(operation.request.content_type if operation.request else None, path, f"{operation.id}.request.content_type", diagnostics)
                self._check_content_type(operation.response.content_type, path, f"{operation.id}.response.content_type", diagnostics)
                if operation.request and operation.request.body and not operation.request.content_type:
                    diagnostics.append(Diagnostic("missing_request_content_type", "request content_type is required when body is declared", path, location=f"{operation.id}.request"))
                self._check_duplicates([str(error.http_status) for error in operation.errors], "error_status", path, diagnostics, f"{operation.id}.errors")
                if operation.request:
                    for section_name in ("query", "header", "body"):
                        container = getattr(operation.request, section_name)
                        if container:
                            location = f"{operation.id}.request.{section_name}"
                            self._check_required(container.fields, container.required, path, location, diagnostics)
                            self._validate_fields(container.fields, objects, catalog, path, f"{location}.fields", diagnostics, require_id=True)
                if operation.response.control:
                    self._validate_fields(operation.response.control.fields, objects, catalog, path, f"{operation.id}.response.control.fields", diagnostics, require_id=True)
                if operation.response.data.fields:
                    self._validate_fields(operation.response.data.fields, objects, catalog, path, f"{operation.id}.response.data.fields", diagnostics, require_id=True)
        return diagnostics

    @staticmethod
    def _check_duplicates(values: list[str], kind: str, path: Path, diagnostics: list[Diagnostic], location: str | None = None) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                diagnostics.append(Diagnostic(f"duplicate_{kind}", f"duplicate {kind} '{value}'", path, location=location))
            seen.add(value)

    @staticmethod
    def _check_required(fields: list, required: list[str], path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        RegistryValidator._check_duplicates(required, "required_field", path, diagnostics, location)
        field_ids = {field.id for field in fields}
        for field_id in required:
            if field_id not in field_ids:
                diagnostics.append(
                    Diagnostic(
                        "unknown_required_field",
                        f"required field '{field_id}' is not declared in fields",
                        path,
                        location=location,
                    )
                )

    def _validate_fields(
        self,
        fields: list,
        objects: dict,
        catalog: RegistryCatalog,
        path: Path,
        location: str,
        diagnostics: list[Diagnostic],
        *,
        require_id: bool,
    ) -> None:
        ids = [field.id for field in fields if field.id is not None]
        self._check_duplicates(ids, "field", path, diagnostics, location)
        for index, field in enumerate(fields):
            field_location = f"{location}.{field.id or index}"
            if require_id and not field.id:
                diagnostics.append(Diagnostic("missing_field_id", "field id is required", path, location=field_location))
            if field.ref and field.ref not in objects:
                diagnostics.append(Diagnostic("unknown_ref", f"unknown local object ref '{field.ref}'", path, location=field_location))
            if field.format:
                format_definition = catalog.formats.get(field.format)
                if not format_definition:
                    diagnostics.append(Diagnostic("unknown_format", f"unknown format '{field.format}'", path, location=field_location))
                elif field.type and field.type != format_definition.base_type:
                    diagnostics.append(Diagnostic("format_type_mismatch", f"format '{field.format}' requires type '{format_definition.base_type}', got '{field.type}'", path, location=field_location))
            if field.default is not None:
                self._check_value_type(field.default, field.type, "default_type_mismatch", path, field_location, diagnostics)
                allowed_values = {value.value for value in field.values}
                if allowed_values and str(field.default) not in allowed_values:
                    diagnostics.append(Diagnostic("default_not_in_values", f"default '{field.default}' is not one of the declared values", path, location=field_location))
            value_ids = [value.value for value in field.values]
            self._check_duplicates(value_ids, "value", path, diagnostics, field_location)

            if field.fields:
                self._check_required(field.fields, field.required, path, field_location, diagnostics)
                self._validate_fields(field.fields, objects, catalog, path, f"{field_location}.fields", diagnostics, require_id=True)
            elif field.required:
                referenced_fields = objects[field.ref].fields if field.ref in objects else []
                self._check_required(referenced_fields, field.required, path, field_location, diagnostics)
            if field.items:
                self._validate_fields([field.items], objects, catalog, path, f"{field_location}.items", diagnostics, require_id=False)

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

    @staticmethod
    def _check_content_type(value: str | None, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        if value is not None and "/" not in value:
            diagnostics.append(Diagnostic("invalid_content_type", f"invalid content type '{value}'", path, location=location))

    @staticmethod
    def _check_circular_refs(objects: dict, path: Path, diagnostics: list[Diagnostic]) -> None:
        def refs_in(fields: list) -> set[str]:
            refs: set[str] = set()
            for field in fields:
                if field.ref:
                    refs.add(field.ref)
                refs.update(refs_in(field.fields))
                if field.items:
                    refs.update(refs_in([field.items]))
            return refs

        graph = {object_id: refs_in(obj.fields) & objects.keys() for object_id, obj in objects.items()}
        visited: set[str] = set()
        active: list[str] = []

        def visit(object_id: str) -> None:
            if object_id in active:
                cycle = active[active.index(object_id):] + [object_id]
                diagnostics.append(Diagnostic("circular_ref", f"circular object reference: {' -> '.join(cycle)}", path, location=f"source.components.objects.{object_id}"))
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
