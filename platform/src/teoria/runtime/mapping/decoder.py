from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from teoria.runtime.mapping.codec import apply_codec
from teoria_provider.models import ExecutionResponse, PreparedRequest
from teoria.registry.loader import RegistryCatalog


class MappedFragment(BaseModel):
    mapping_id: str
    operation: str
    record_key: str
    record_order: str | None = None
    ontology: str
    object_type: str
    role: str
    properties: dict[str, Any]


class MappingDecoder:
    def decode_database_rows(
        self,
        catalog: RegistryCatalog,
        source_id: str,
        relation_id: str,
        rows: list[dict[str, Any]],
    ) -> list[MappedFragment]:
        source = catalog.sources[source_id].source
        relation = next(item for item in source.relations if item.id == relation_id)
        call = f"{source_id}.{relation_id}"
        prefix = f"{call}."
        results: list[MappedFragment] = []

        for record_index, row in enumerate(rows):
            record_key = ":".join(str(row.get(key, "")) for key in relation.primary_key)
            for mapping_id, mapping in catalog.mappings.items():
                materialization = mapping.materializations.get(call)
                if materialization is None:
                    continue
                fragments: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
                for target, bindings in mapping.bindings.items():
                    target_parts = target.split(".")
                    object_type = ".".join(target_parts[:-1])
                    property_id = target_parts[-1]
                    for binding in bindings:
                        references = (
                            [binding.field]
                            if isinstance(binding.field, str)
                            else list(binding.field.values())
                        )
                        if not references or not all(reference.startswith(prefix) for reference in references):
                            continue
                        if isinstance(binding.field, str):
                            raw = row.get(binding.field[len(prefix):])
                        else:
                            raw = {
                                name: row.get(reference[len(prefix):])
                                for name, reference in binding.field.items()
                            }
                        value = apply_codec(binding.decode, raw)
                        if value is None or value == "":
                            continue
                        role = binding.role or object_type
                        fragments[(role, object_type)][property_id] = value
                        fragments[(role, object_type)].update(binding.qualifiers)

                order = row.get(materialization.record_order) if materialization.record_order else None
                for (role, object_type), properties in fragments.items():
                    results.append(MappedFragment(
                        mapping_id=mapping_id,
                        operation=call,
                        record_key=f"{call}:{record_key or record_index}",
                        record_order=str(order) if order is not None else None,
                        ontology=mapping.ontology,
                        object_type=object_type,
                        role=role,
                        properties=properties,
                    ))
        return results

    def decode(
        self,
        catalog: RegistryCatalog,
        source_id: str,
        operation_id: str,
        response: ExecutionResponse,
        request: PreparedRequest | None = None,
        record_key_prefix: str = "0",
    ) -> list[MappedFragment]:
        source = catalog.sources[source_id]
        operation = next(item for item in source.source.operations if item.id == operation_id)
        try:
            records = self._resolve_path(response.body, operation.response.data.record_path)
        except (KeyError, TypeError):
            if not operation.pagination or int(self._resolve_path(
                response.body, operation.pagination.total_count, missing=-1
            )) != 0:
                raise
            records = []
        if not isinstance(records, list):
            records = [records]
        call = f"{source_id}.{operation_id}"
        response_prefix = f"{call}.response."
        request_prefix = f"{call}.request."
        results: list[MappedFragment] = []

        for record_index, record in enumerate(records):
            for mapping_id, mapping in catalog.mappings.items():
                materialization = mapping.materializations.get(call)
                if materialization is None:
                    continue
                base: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
                variants: dict[tuple[str, str], dict[tuple[tuple[str, str], ...], dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
                for target, bindings in mapping.bindings.items():
                    target_parts = target.split(".")
                    object_type = ".".join(target_parts[:-1])
                    property_id = target_parts[-1]
                    for binding in bindings:
                        references = [binding.field] if isinstance(binding.field, str) else list(binding.field.values())
                        if not references or not all(
                            reference.startswith((response_prefix, request_prefix)) for reference in references
                        ):
                            continue
                        if isinstance(binding.field, str):
                            raw = self._binding_value(
                                binding.field, record, request, response_prefix, request_prefix
                            )
                        else:
                            raw = {
                                name: self._binding_value(
                                    reference, record, request, response_prefix, request_prefix
                                )
                                for name, reference in binding.field.items()
                            }
                        value = apply_codec(binding.decode, raw)
                        if value is None or value == "":
                            continue
                        role = binding.role or object_type
                        key = (role, object_type)
                        if (
                            isinstance(binding.field, str)
                            and binding.field.startswith(request_prefix)
                            and property_id in base[key]
                        ):
                            continue
                        if binding.qualifiers:
                            variants[key][tuple(sorted(binding.qualifiers.items()))][property_id] = value
                        else:
                            base[key][property_id] = value

                order = self._resolve_path(record, materialization.record_order, missing=None) if materialization.record_order else None
                for key in base.keys() | variants.keys():
                    role, object_type = key
                    property_sets = []
                    if variants[key]:
                        for qualifier_key, properties in variants[key].items():
                            combined = dict(base[key])
                            combined.update(dict(qualifier_key))
                            combined.update(properties)
                            property_sets.append(combined)
                    elif base[key]:
                        property_sets.append(dict(base[key]))
                    for properties in property_sets:
                        results.append(
                            MappedFragment(
                                mapping_id=mapping_id,
                                operation=call,
                                record_key=f"{call}:{record_key_prefix}:{record_index}",
                                record_order=str(order) if order is not None else None,
                                ontology=mapping.ontology,
                                object_type=object_type,
                                role=role,
                                properties=properties,
                            )
                        )
        return results

    def _binding_value(
        self, reference: str, record: Any, request: PreparedRequest | None,
        response_prefix: str, request_prefix: str,
    ) -> Any:
        if reference.startswith(response_prefix):
            return self._resolve_path(record, reference[len(response_prefix):], missing=None)
        if request is None:
            return None
        return self._resolve_path(
            request.model_dump(), reference[len(request_prefix):], missing=None
        )

    @staticmethod
    def _resolve_path(value: Any, path: str | None, missing: Any = ...):
        current = value
        if not path:
            return current
        for raw_segment in path.split("."):
            is_collection = raw_segment.endswith("[]")
            segment = raw_segment[:-2] if is_collection else raw_segment
            if not isinstance(current, dict) or segment not in current:
                if missing is not ...:
                    return missing
                if is_collection:
                    return []
                raise KeyError(segment)
            current = current[segment]
            if is_collection and not isinstance(current, list):
                current = [current]
        return current
