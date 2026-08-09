import types
from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from teoria.registry.diagnostics import Diagnostic
from teoria.registry.loader import RegistryCatalog
from teoria.registry.validation import validate_ontologies, validate_references, validate_value_sets
from teoria.registry.validation.duplicates import check_duplicates
from teoria_provider.validator import ProviderContractValidator

BUILTIN_DATA_TYPES = {"string", "integer", "number", "boolean"}
ONTOLOGY_BUILTIN_DATA_TYPES = BUILTIN_DATA_TYPES | {"date", "datetime"}


class RegistryValidator:
    def validate(
        self,
        catalog: RegistryCatalog,
        source_id: str | None = None,
    ) -> list[Diagnostic]:
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
            if path.stem != source.id:
                diagnostics.append(Diagnostic("source_filename_mismatch", f"filename must match source id '{source.id}.yaml'", path, location="source.id"))
            if source.type == "api":
                self._validate_api_contract(source, catalog, path, "source", diagnostics)
            else:
                self._validate_database_source(source, catalog, path, diagnostics)

        validate_value_sets(catalog, diagnostics)
        validate_references(catalog, diagnostics)
        validate_ontologies(catalog, diagnostics)
        self._validate_mappings(catalog, diagnostics)
        self._validate_capabilities(catalog, diagnostics)
        return diagnostics

    def validate_api_definition(self, source: Any, catalog: RegistryCatalog, path: Path, *, root: str) -> list[Diagnostic]:
        """Validate a provider API contract owned outside the Semantic Registry."""

        diagnostics: list[Diagnostic] = []
        self._validate_api_contract(source, catalog, path, root, diagnostics)
        return diagnostics

    def _validate_api_contract(
        self,
        source: Any,
        catalog: RegistryCatalog,
        path: Path,
        root: str,
        diagnostics: list[Diagnostic],
    ) -> None:
        diagnostics.extend(
            ProviderContractValidator().validate(
                source,
                data_types=catalog.data_types,
                path=path,
                root=root,
            )
        )

    def _validate_database_source(
        self,
        source: Any,
        catalog: RegistryCatalog,
        path: Path,
        diagnostics: list[Diagnostic],
    ) -> None:
        self._check_duplicates([item.id for item in source.relations], "relation", path, diagnostics)
        self._check_duplicates([item.relation for item in source.relations], "database_relation", path, diagnostics)
        for relation in source.relations:
            location = f"source.relations.{relation.id}"
            self._validate_fields(
                relation.fields,
                {},
                catalog,
                path,
                f"{location}.fields",
                diagnostics,
                require_id=True,
                allowed_builtin_types=ONTOLOGY_BUILTIN_DATA_TYPES,
            )
            self._check_required(relation.fields, relation.primary_key, path, location, diagnostics)

    def _validate_capabilities(self, catalog: RegistryCatalog, diagnostics: list[Diagnostic]) -> None:
        for capability_id, capability in catalog.capabilities.items():
            path = catalog.capability_paths[capability_id]
            if path.stem != capability.id:
                diagnostics.append(Diagnostic("capability_filename_mismatch", f"filename must match capability id '{capability.id}.yaml'", path, location="capability.id"))

            for effect_name in ("reads", "produces", "creates", "updates"):
                for index, reference in enumerate(getattr(capability.effects, effect_name)):
                    location = f"capability.effects.{effect_name}.{index}"
                    parts = reference.split(".")
                    ontology = catalog.ontologies.get(parts[0])
                    obj = next(
                        (item for item in ontology.object_types if item.id == parts[1]),
                        None,
                    ) if ontology and len(parts) in {2, 3} else None
                    if obj is None:
                        diagnostics.append(Diagnostic("unknown_capability_effect", f"unknown ontology object '{reference}'", path, location=location))
                    elif len(parts) == 3 and parts[2] not in {item.id for item in obj.properties}:
                        diagnostics.append(Diagnostic("unknown_capability_effect", f"unknown ontology property '{reference}'", path, location=location))

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
                operation = next(
                    (item for item in source.source.operations if item.id == operation_id),
                    None,
                ) if source and source.source.type == "api" else None
                relation = next(
                    (item for item in source.source.relations if item.id == operation_id),
                    None,
                ) if source and source.source.type == "database" else None
                if operation is None and relation is None:
                    diagnostics.append(Diagnostic("unknown_capability_operation", f"unknown source operation '{step.call}'", path, location=f"{location}.call"))
                    continue
                if relation is not None:
                    relation_prefix = f"{step.call}."
                    for input_id, input_definition in input_leaves:
                        if input_definition.field:
                            if not input_definition.field.startswith(relation_prefix):
                                diagnostics.append(Diagnostic("capability_input_field_operation_mismatch", f"field '{input_definition.field}' does not belong to '{step.call}'", path, location=location))
                            else:
                                self._validate_mapping_source_ref(input_definition.field, catalog, path, location, diagnostics)
                        elif input_definition.property:
                            ontology_id, object_id, property_id = input_definition.property.split(".")
                            target = f"{object_id}.{property_id}"
                            matches = [
                                binding
                                for mapping in catalog.mappings.values()
                                if mapping.ontology == ontology_id
                                for binding in mapping.bindings.get(target, [])
                                if any(ref.startswith(relation_prefix) for ref in self._mapping_field_refs(binding.field))
                            ]
                            if len(matches) != 1:
                                diagnostics.append(Diagnostic("missing_capability_input_binding", f"input '{input_id}' must have exactly one database binding for '{step.call}'", path, location=location))
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
                operation_prefixes = tuple(
                    prefix
                    for step in capability.steps
                    for prefix in (
                        (f"{step.call}.response.", f"{step.call}.request.")
                        if catalog.sources[step.call.split('.', 1)[0]].source.type == "api"
                        else (f"{step.call}.",)
                    )
                )
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
                if capability.kind == "query" and not has_response_binding:
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
                if len(parts) == 2:
                    target_ontology = ontology
                    object_id, property_id = parts
                elif len(parts) == 3 and parts[0] in catalog.ontologies:
                    target_ontology = catalog.ontologies[parts[0]]
                    object_id, property_id = parts[1:]
                else:
                    diagnostics.append(Diagnostic("unknown_mapping_target", f"unknown mapping target '{target}'", path, location=location))
                    continue
                obj = next(
                    (item for item in target_ontology.object_types if item.id == object_id),
                    None,
                )
                if obj is None:
                    diagnostics.append(Diagnostic("unknown_mapping_target", f"unknown mapping target '{target}'", path, location=location))
                    continue
                properties = {item.id: item for item in obj.properties}
                if property_id not in properties:
                    diagnostics.append(Diagnostic("unknown_mapping_target", f"unknown property '{property_id}' on object type '{object_id}'", path, location=location))
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
                        module_name = f"teoria.runtime.mapping.functions.{transform_module}"
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
                    self._validate_binding_types(rule, properties[property_id], catalog, path, rule_location, diagnostics)

            link_types = {item.id: item for item in ontology.link_types}
            for operation_ref, materialization in mapping.materializations.items():
                location = f"mapping.materializations.{operation_ref}"
                parts = operation_ref.split(".")
                source = catalog.sources.get(parts[0]) if len(parts) == 2 else None
                target_exists = False
                if source and source.source.type == "api":
                    target_exists = any(item.id == parts[1] for item in source.source.operations)
                elif source and source.source.type == "database":
                    target_exists = any(item.id == parts[1] for item in source.source.relations)
                if not target_exists:
                    diagnostics.append(Diagnostic("unknown_materialization_operation", f"unknown source operation or relation '{operation_ref}'", path, location=location))
                roles = set(materialization.objects)
                for role, spec in materialization.objects.items():
                    if "." in spec.type:
                        object_ontology_id, object_type_id = spec.type.split(".", 1)
                        object_ontology = catalog.ontologies.get(object_ontology_id)
                        obj = next(
                            (item for item in object_ontology.object_types if item.id == object_type_id),
                            None,
                        ) if object_ontology else None
                    else:
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
        if len(parts) < 3:
            diagnostics.append(Diagnostic("invalid_mapping_source", f"source reference '{reference}' is incomplete", path, location=location))
            return
        source = catalog.sources.get(parts[0])
        if source is None:
            diagnostics.append(Diagnostic("unknown_mapping_source", f"unknown source '{parts[0]}'", path, location=location))
            return
        if source.source.type == "database":
            relation = next((item for item in source.source.relations if item.id == parts[1]), None)
            if relation is None:
                diagnostics.append(Diagnostic("unknown_mapping_relation", f"unknown relation '{parts[1]}' on source '{parts[0]}'", path, location=location))
                return
            fields = relation.fields
            field_parts = parts[2:]
            for index, field_id in enumerate(field_parts):
                field = next((item for item in fields if item.id == field_id), None)
                if field is None:
                    diagnostics.append(Diagnostic("unknown_mapping_field", f"unknown field '{field_id}' in '{reference}'", path, location=location))
                    return
                if index < len(field_parts) - 1:
                    fields = field.fields
            return
        if len(parts) < 4:
            diagnostics.append(Diagnostic("invalid_mapping_source", f"API source reference '{reference}' is incomplete", path, location=location))
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
        is_decode = bool(
            references
            and (
                ".response." in references[0]
                or (
                    references[0].split(".", 1)[0] in catalog.sources
                    and catalog.sources[references[0].split(".", 1)[0]].source.type == "database"
                )
            )
        )
        codec_path = binding.decode if is_decode else binding.encode
        if codec_path is None:
            if len(source_categories) == 1 and source_categories[0] and not self._categories_compatible(source_categories[0], target_category):
                diagnostics.append(Diagnostic("mapping_type_mismatch", f"field type '{source_categories[0]}' is incompatible with ontology type '{target_category}'", path, location=location))
            return
        try:
            module_name, function_name = codec_path.rsplit(".", 1)
            function = getattr(import_module(f"teoria.runtime.mapping.functions.{module_name}"), function_name)
            hints = get_type_hints(function)
            return_categories = self._annotation_categories(hints.get("return"))
            expected_return = target_category if is_decode else (source_categories[0] if len(source_categories) == 1 else None)
            if expected_return and return_categories and not any(self._categories_compatible(category, expected_return) for category in return_categories):
                diagnostics.append(Diagnostic("codec_return_type_mismatch", f"codec '{codec_path}' returns {sorted(return_categories)}, expected '{expected_return}'", path, location=location))
            parameters = [item for item in signature(function).parameters.values() if item.kind not in {Parameter.VAR_KEYWORD, Parameter.VAR_POSITIONAL}]
            if isinstance(binding.field, str) and parameters:
                input_categories = self._annotation_categories(hints.get(parameters[0].name))
                expected_input = source_categories[0] if is_decode else target_category
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

    @staticmethod
    def _check_duplicates(values: list[str], kind: str, path: Path, diagnostics: list[Diagnostic], location: str | None = None) -> None:
        check_duplicates(values, kind, path, diagnostics, location)

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
            value_ids = [value.value for value in field.values]
            self._check_duplicates(value_ids, "value", path, diagnostics, field_location)

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
