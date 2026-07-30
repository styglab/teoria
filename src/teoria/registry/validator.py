import re
import types
from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog

RECORD_PATH_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$")
BUILTIN_DATA_TYPES = {"string", "integer", "number", "boolean"}
ONTOLOGY_BUILTIN_DATA_TYPES = BUILTIN_DATA_TYPES | {"date", "datetime"}


class RegistryValidator:
    def validate(self, catalog: RegistryCatalog, source_id: str | None = None) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        registries = catalog.sources.items()
        if source_id is not None:
            registry = catalog.sources.get(source_id)
            if registry is None:
                return [Diagnostic("unknown_source", f"unknown source '{source_id}'", catalog.root / "sources")]
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
                    control = operation.response.control
                    if control.record_path != "." and not RECORD_PATH_PATTERN.fullmatch(control.record_path):
                        diagnostics.append(Diagnostic("invalid_record_path", f"invalid control record path '{control.record_path}'", path, location=f"{operation.id}.response.control.record_path"))
                    if control.success.field not in {field.id for field in control.fields}:
                        diagnostics.append(Diagnostic("unknown_control_success_field", f"unknown control success field '{control.success.field}'", path, location=f"{operation.id}.response.control.success"))
                    self._validate_fields(operation.response.control.fields, objects, catalog, path, f"{operation.id}.response.control.fields", diagnostics, require_id=True)
                if operation.response.data.fields:
                    self._validate_fields(operation.response.data.fields, objects, catalog, path, f"{operation.id}.response.data.fields", diagnostics, require_id=True)
        self._validate_value_sets(catalog, diagnostics)
        self._validate_references(catalog, diagnostics)
        self._validate_ontologies(catalog, diagnostics)
        self._validate_mappings(catalog, diagnostics)
        self._validate_capabilities(catalog, diagnostics)
        return diagnostics

    def _validate_references(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        project_root = catalog.root.parent.resolve()
        for source_id, source_registry in catalog.sources.items():
            source_document = source_registry.source.specification.source_document
            reference = catalog.references.get(source_id)
            if source_document and reference is None:
                diagnostics.append(
                    Diagnostic(
                        "missing_source_reference",
                        f"source '{source_id}' declares source_document but has no provider reference metadata",
                        catalog.source_paths[source_id],
                        location="source.specification.source_document",
                    )
                )
                continue
            if reference is None:
                continue
            metadata_path = catalog.reference_paths[source_id]
            registry_path = (project_root / reference.registry).resolve()
            expected_registry_path = catalog.source_paths[source_id].resolve()
            if registry_path != expected_registry_path:
                diagnostics.append(
                    Diagnostic(
                        "reference_registry_mismatch",
                        f"reference registry points to '{reference.registry}', expected '{catalog.source_paths[source_id]}'",
                        metadata_path,
                        location="registry",
                    )
                )
            file_names = {item.path for item in reference.files}
            for index, item in enumerate(reference.files):
                if not (metadata_path.parent / item.path).is_file():
                    diagnostics.append(
                        Diagnostic(
                            "reference_file_not_found",
                            f"reference file '{item.path}' does not exist",
                            metadata_path,
                            location=f"files.{index}.path",
                        )
                    )
            if source_document and source_document not in file_names:
                diagnostics.append(
                    Diagnostic(
                        "source_document_mismatch",
                        f"source_document '{source_document}' is not listed in provider reference files",
                        catalog.source_paths[source_id],
                        location="source.specification.source_document",
                    )
                )

        for source_id, reference in catalog.references.items():
            if source_id not in catalog.sources:
                diagnostics.append(
                    Diagnostic(
                        "unknown_reference_source",
                        f"provider reference points to unknown source '{reference.source}'",
                        catalog.reference_paths[source_id],
                        location="source",
                    )
                )

    def _validate_capabilities(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        for capability_id, capability in catalog.capabilities.items():
            path = catalog.capability_paths[capability_id]
            if path.stem != capability.id:
                diagnostics.append(Diagnostic("capability_filename_mismatch", f"filename must match capability id '{capability.id}.yaml'", path, location="capability.id"))

            input_leaves = list(self._capability_input_leaves(capability.inputs))
            for input_id, input_definition in input_leaves:
                location = f"capability.inputs.{input_id}"
                if input_definition.data_type and input_definition.data_type not in ONTOLOGY_BUILTIN_DATA_TYPES and input_definition.data_type not in catalog.data_types:
                    diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{input_definition.data_type}'", path, location=location))
                if input_definition.property:
                    parts = input_definition.property.split(".")
                    ontology = catalog.ontologies.get(parts[0]) if len(parts) == 3 else None
                    obj = next((item for item in ontology.object_types if item.id == parts[1]), None) if ontology else None
                    if obj is None or parts[2] not in {item.id for item in obj.properties}:
                        diagnostics.append(Diagnostic("unknown_capability_input_property", f"unknown ontology property '{input_definition.property}'", path, location=location))

            for index, step in enumerate(capability.steps):
                location = f"capability.steps.{index}"
                source_id, operation_id = step.call.split(".")
                source = catalog.sources.get(source_id)
                operation = next((item for item in source.source.operations if item.id == operation_id), None) if source else None
                if operation is None:
                    diagnostics.append(Diagnostic("unknown_capability_operation", f"unknown source operation '{step.call}'", path, location=f"{location}.call"))
                    continue
                request_prefix = f"{step.call}.request."
                for input_id, input_definition in input_leaves:
                    if input_definition.property:
                        ontology_id, object_id, property_id = input_definition.property.split(".")
                        target = f"{object_id}.{property_id}"
                        bindings = [
                            binding
                            for mapping in catalog.mappings.values()
                            if mapping.ontology == ontology_id
                            for binding in mapping.bindings.get(target, [])
                        ]
                        if not any(reference.startswith(request_prefix) for binding in bindings for reference in self._mapping_field_refs(binding.field)):
                            diagnostics.append(Diagnostic("missing_capability_input_binding", f"input '{input_id}' has no request binding for '{step.call}'", path, location=location))
                    elif input_definition.field:
                        if not input_definition.field.startswith(request_prefix):
                            diagnostics.append(Diagnostic("capability_input_field_operation_mismatch", f"field '{input_definition.field}' does not belong to '{step.call}'", path, location=location))
                        else:
                            self._validate_mapping_source_ref(input_definition.field, catalog, path, location, diagnostics)

            for index, reference in enumerate(capability.returns):
                parts = reference.split(".")
                ontology = catalog.ontologies.get(parts[0]) if len(parts) == 2 else None
                known = set()
                if ontology:
                    known = {item.id for item in ontology.object_types} | {item.id for item in ontology.link_types}
                if ontology is None or parts[1] not in known:
                    diagnostics.append(Diagnostic("unknown_capability_return", f"unknown ontology object or link '{reference}'", path, location=f"capability.returns.{index}"))
                    continue
                if parts[1] in {item.id for item in ontology.link_types}:
                    continue
                operation_prefixes = tuple(f"{step.call}.response." for step in capability.steps)
                has_response_binding = any(
                    mapping.ontology == parts[0]
                    and target.startswith(f"{parts[1]}.")
                    and any(
                        field.startswith(operation_prefixes)
                        for binding in bindings
                        for field in self._mapping_field_refs(binding.field)
                    )
                    for mapping in catalog.mappings.values()
                    for target, bindings in mapping.bindings.items()
                )
                if not has_response_binding:
                    diagnostics.append(Diagnostic("unavailable_capability_return", f"no called operation provides response bindings for '{reference}'", path, location=f"capability.returns.{index}"))

    @staticmethod
    def _capability_input_leaves(inputs: dict, prefix: str = ""):
        for input_id, definition in inputs.items():
            path = f"{prefix}.{input_id}" if prefix else input_id
            if definition.fields:
                yield from RegistryValidator._capability_input_leaves(definition.fields, path)
            else:
                yield path, definition

    @staticmethod
    def _field_path_exists(fields: list, parts: list[str], source: Any) -> bool:
        objects = {item.id: item for item in source.source.components.objects}
        for index, field_id in enumerate(parts):
            field = next((item for item in fields if item.id == field_id), None)
            if field is None:
                return False
            if index < len(parts) - 1:
                if field.ref in objects:
                    fields = objects[field.ref].fields
                elif field.items and field.items.ref in objects:
                    fields = objects[field.items.ref].fields
                else:
                    fields = field.fields
        return True

    def _validate_mappings(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        for mapping_id, mapping in catalog.mappings.items():
            path = catalog.mapping_paths[mapping_id]
            if path.stem != mapping.id:
                diagnostics.append(Diagnostic("mapping_filename_mismatch", f"filename must match mapping id '{mapping.id}.yaml'", path, location="mapping.id"))
            ontology = catalog.ontologies.get(mapping.ontology)
            if ontology is None:
                diagnostics.append(Diagnostic("unknown_mapping_ontology", f"unknown ontology '{mapping.ontology}'", path, location="mapping.ontology"))
                continue
            object_types = {item.id: item for item in ontology.object_types}
            for target, rules in mapping.bindings.items():
                parts = target.split(".")
                location = f"mapping.bindings.{target}"
                if len(parts) != 2 or parts[0] not in object_types:
                    diagnostics.append(Diagnostic("unknown_mapping_target", f"unknown mapping target '{target}'", path, location=location))
                    continue
                obj = object_types[parts[0]]
                properties = {item.id: item for item in obj.properties}
                if parts[1] not in properties:
                    diagnostics.append(Diagnostic("unknown_mapping_target", f"unknown property '{parts[1]}' on object type '{parts[0]}'", path, location=location))
                    continue
                for index, rule in enumerate(rules):
                    rule_location = f"{location}.{index}"
                    field_refs = self._mapping_field_refs(rule.field)
                    for source_ref in field_refs:
                        self._validate_mapping_source_ref(source_ref, catalog, path, rule_location, diagnostics)
                    for qualifier, value in rule.qualifiers.items():
                        prop = properties.get(qualifier)
                        if prop is None:
                            diagnostics.append(Diagnostic("unknown_mapping_qualifier", f"unknown qualifier property '{qualifier}'", path, location=rule_location))
                        elif prop.value_set in catalog.value_sets and value not in {item.id for item in catalog.value_sets[prop.value_set].values}:
                            diagnostics.append(Diagnostic("invalid_mapping_qualifier", f"value '{value}' is not in value set '{prop.value_set}'", path, location=rule_location))
                    for codec_name, codec_path in (("decode", rule.decode), ("encode", rule.encode)):
                        if not codec_path:
                            continue
                        transform_module, function_name = codec_path.rsplit(".", 1)
                        module_name = f"teoria.transforms.{transform_module}"
                        try:
                            function = getattr(import_module(module_name), function_name)
                            if not callable(function):
                                raise TypeError("not callable")
                            if isinstance(rule.field, dict):
                                parameters = signature(function).parameters
                                accepts_kwargs = any(item.kind == Parameter.VAR_KEYWORD for item in parameters.values())
                                missing = set(rule.field) - set(parameters)
                                if missing and not accepts_kwargs:
                                    diagnostics.append(Diagnostic("codec_input_mismatch", f"{codec_name} codec '{codec_path}' does not accept inputs {sorted(missing)}", path, location=rule_location))
                        except (ImportError, AttributeError, TypeError) as exc:
                            diagnostics.append(Diagnostic("unknown_codec", f"cannot resolve {codec_name} codec '{codec_path}': {exc}", path, location=rule_location))
                    self._validate_binding_types(rule, properties[parts[1]], catalog, path, rule_location, diagnostics)

            link_types = {item.id: item for item in ontology.link_types}
            for operation_ref, materialization in mapping.materializations.items():
                location = f"mapping.materializations.{operation_ref}"
                parts = operation_ref.split(".")
                source = catalog.sources.get(parts[0]) if len(parts) == 2 else None
                operation = next((item for item in source.source.operations if item.id == parts[1]), None) if source else None
                if operation is None:
                    diagnostics.append(Diagnostic("unknown_materialization_operation", f"unknown source operation '{operation_ref}'", path, location=location))
                roles = set(materialization.objects)
                for role, spec in materialization.objects.items():
                    obj = object_types.get(spec.type)
                    if obj is None:
                        diagnostics.append(Diagnostic("unknown_materialization_object", f"unknown object type '{spec.type}'", path, location=f"{location}.objects.{role}"))
                        continue
                    properties = {item.id for item in obj.properties}
                    for property_id in spec.identity:
                        if property_id not in properties:
                            diagnostics.append(Diagnostic("unknown_materialization_identity", f"unknown identity property '{property_id}' on '{spec.type}'", path, location=f"{location}.objects.{role}.identity"))
                    for property_id in ([spec.id_property] if spec.id_property else []) + spec.timestamp_properties:
                        if property_id and property_id not in properties:
                            diagnostics.append(Diagnostic("unknown_materialization_property", f"unknown property '{property_id}' on '{spec.type}'", path, location=f"{location}.objects.{role}"))
                    for parent in spec.parents:
                        if parent not in roles:
                            diagnostics.append(Diagnostic("unknown_materialization_parent", f"unknown parent role '{parent}'", path, location=f"{location}.objects.{role}.parents"))
                for index, link in enumerate(materialization.links):
                    if link.type not in link_types:
                        diagnostics.append(Diagnostic("unknown_materialization_link", f"unknown link type '{link.type}'", path, location=f"{location}.links.{index}"))
                    for endpoint in (link.source, link.target):
                        if endpoint not in roles:
                            diagnostics.append(Diagnostic("unknown_materialization_role", f"unknown object role '{endpoint}'", path, location=f"{location}.links.{index}"))

    @staticmethod
    def _mapping_field_refs(field: Any) -> list[str]:
        if isinstance(field, str):
            return [field]
        refs: list[str] = []
        for value in field.values():
            if isinstance(value, str):
                refs.append(value)
        return refs

    def _validate_mapping_source_ref(self, reference: str, catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        parts = reference.split(".")
        if len(parts) < 4:
            diagnostics.append(Diagnostic("invalid_mapping_source", f"source reference '{reference}' is incomplete", path, location=location))
            return
        source = catalog.sources.get(parts[0])
        if source is None:
            diagnostics.append(Diagnostic("unknown_mapping_source", f"unknown source '{parts[0]}'", path, location=location))
            return
        operation = next((item for item in source.source.operations if item.id == parts[1]), None)
        if operation is None:
            diagnostics.append(Diagnostic("unknown_mapping_operation", f"unknown operation '{parts[1]}' on source '{parts[0]}'", path, location=location))
            return
        objects = {item.id: item for item in source.source.components.objects}
        section = parts[2]
        if section == "response":
            fields = objects[operation.response.data.ref].fields if operation.response.data.ref else operation.response.data.fields
            field_parts = parts[3:]
        elif section == "request" and operation.request and len(parts) >= 5 and parts[3] in {"query", "header", "body"}:
            container = getattr(operation.request, parts[3])
            fields = container.fields if container else []
            field_parts = parts[4:]
        else:
            diagnostics.append(Diagnostic("invalid_mapping_source", f"invalid source section in '{reference}'", path, location=location))
            return
        for index, raw_field_id in enumerate(field_parts):
            field_id = raw_field_id[:-2] if raw_field_id.endswith("[]") else raw_field_id
            field = next((item for item in fields if item.id == field_id), None)
            if field is None:
                diagnostics.append(Diagnostic("unknown_mapping_field", f"unknown field '{field_id}' in '{reference}'", path, location=location))
                return
            if index < len(field_parts) - 1:
                if field.ref and field.ref in objects:
                    fields = objects[field.ref].fields
                elif field.items and field.items.ref and field.items.ref in objects:
                    fields = objects[field.items.ref].fields
                else:
                    fields = field.fields

    def _validate_binding_types(self, binding: Any, ontology_property: Any, catalog: RegistryCatalog, path: Path, location: str, diagnostics: list[Diagnostic]) -> None:
        references = self._mapping_field_refs(binding.field)
        source_categories = [self._source_field_category(reference, catalog) for reference in references]
        target_category = self._ontology_property_category(ontology_property, catalog)
        is_response = bool(references and ".response." in references[0])
        codec_path = binding.decode if is_response else binding.encode
        if codec_path is None:
            if len(source_categories) == 1 and source_categories[0] and not self._categories_compatible(source_categories[0], target_category):
                diagnostics.append(Diagnostic("mapping_type_mismatch", f"field type '{source_categories[0]}' is incompatible with ontology type '{target_category}'", path, location=location))
            return
        try:
            module_name, function_name = codec_path.rsplit(".", 1)
            function = getattr(import_module(f"teoria.transforms.{module_name}"), function_name)
            hints = get_type_hints(function)
            return_categories = self._annotation_categories(hints.get("return"))
            expected_return = target_category if is_response else (source_categories[0] if len(source_categories) == 1 else None)
            if expected_return and return_categories and not any(self._categories_compatible(category, expected_return) for category in return_categories):
                diagnostics.append(Diagnostic("codec_return_type_mismatch", f"codec '{codec_path}' returns {sorted(return_categories)}, expected '{expected_return}'", path, location=location))
            parameters = [item for item in signature(function).parameters.values() if item.kind not in {Parameter.VAR_KEYWORD, Parameter.VAR_POSITIONAL}]
            if isinstance(binding.field, str) and parameters:
                input_categories = self._annotation_categories(hints.get(parameters[0].name))
                expected_input = source_categories[0] if is_response else target_category
                if input_categories and expected_input and not any(self._categories_compatible(expected_input, category) for category in input_categories):
                    diagnostics.append(Diagnostic("codec_input_type_mismatch", f"codec '{codec_path}' accepts {sorted(input_categories)}, got '{expected_input}'", path, location=location))
            elif isinstance(binding.field, dict):
                for (name, _), source_category in zip(binding.field.items(), source_categories):
                    input_categories = self._annotation_categories(hints.get(name))
                    if input_categories and source_category and not any(self._categories_compatible(source_category, category) for category in input_categories):
                        diagnostics.append(Diagnostic("codec_input_type_mismatch", f"codec '{codec_path}' input '{name}' accepts {sorted(input_categories)}, got '{source_category}'", path, location=location))
        except (ImportError, AttributeError, TypeError, ValueError):
            return

    def _source_field_category(self, reference: str, catalog: RegistryCatalog) -> str | None:
        parts = reference.split(".")
        if len(parts) < 4 or parts[0] not in catalog.sources:
            return None
        source = catalog.sources[parts[0]]
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
            str: "string",
            int: "integer",
            float: "number",
            Decimal: "number",
            bool: "boolean",
            date: "date",
            datetime: "datetime",
            dict: "object",
            Any: "any",
        }.get(annotation)
        return {category} if category else set()

    @staticmethod
    def _categories_compatible(actual: str, expected: str) -> bool:
        if "any" in {actual, expected} or actual == expected:
            return True
        return (actual, expected) == ("integer", "number")

    def _validate_value_sets(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        path = catalog.root / "core" / "value_sets.yaml"
        for value_set in catalog.value_sets.values():
            self._check_duplicates([value.id for value in value_set.values], "value_set_value", path, diagnostics, f"value_sets.{value_set.id}.values")

    def _validate_ontologies(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        for ontology_id, ontology in catalog.ontologies.items():
            path = catalog.ontology_paths[ontology_id]
            domain_ontology = path.name == "ontology.yaml" and path.parent.name == ontology.id
            if path.stem != ontology.id and not domain_ontology:
                diagnostics.append(Diagnostic("ontology_filename_mismatch", f"filename must match ontology id '{ontology.id}.yaml'", path, location="ontology.id"))

            object_types = {item.id: item for item in ontology.object_types}
            link_types = {item.id: item for item in ontology.link_types}
            self._check_duplicates([item.id for item in ontology.object_types], "object_type", path, diagnostics, "ontology.object_types")
            self._check_duplicates([item.id for item in ontology.link_types], "link_type", path, diagnostics, "ontology.link_types")

            for obj in ontology.object_types:
                location = f"ontology.object_types.{obj.id}"
                properties = {prop.id: prop for prop in obj.properties}
                self._check_duplicates([prop.id for prop in obj.properties], "ontology_property", path, diagnostics, f"{location}.properties")
                if obj.primary_key not in properties:
                    diagnostics.append(Diagnostic("unknown_primary_key", f"unknown property '{obj.primary_key}'", path, location=f"{location}.primary_key"))

                for prop in obj.properties:
                    prop_location = f"{location}.properties.{prop.id}"
                    if prop.data_type and prop.data_type not in ONTOLOGY_BUILTIN_DATA_TYPES and prop.data_type not in catalog.data_types:
                        diagnostics.append(Diagnostic("unknown_data_type", f"unknown data type '{prop.data_type}'", path, location=prop_location))
                    if prop.value_set and prop.value_set not in catalog.value_sets:
                        diagnostics.append(Diagnostic("unknown_value_set", f"unknown value set '{prop.value_set}'", path, location=prop_location))

                for example_index, example in enumerate(obj.examples):
                    for property_id in example:
                        if property_id not in properties:
                            diagnostics.append(Diagnostic("unknown_example_property", f"unknown example property '{property_id}'", path, location=f"{location}.examples.{example_index}"))
            for link in ontology.link_types:
                location = f"ontology.link_types.{link.id}"
                for side_name, object_type in (("source", link.source), ("target", link.target)):
                    if object_type not in object_types:
                        diagnostics.append(Diagnostic("unknown_link_object_type", f"unknown object type '{object_type}'", path, location=f"{location}.{side_name}"))


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
            declared_data_type = field.data_type
            resolved_data_type = declared_data_type
            if declared_data_type and declared_data_type not in BUILTIN_DATA_TYPES:
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
