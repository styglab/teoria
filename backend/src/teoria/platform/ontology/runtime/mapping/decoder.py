from collections import defaultdict
from typing import Any
from decimal import Decimal
from datetime import date, datetime, timezone
import hashlib
import json

from pydantic import BaseModel, Field
from teoria.platform.ontology.authoring.value_policy import normalize_property_number

from teoria.platform.ontology.contracts.codecs import apply_codec
from teoria.integrations.provider_api.models import ExecutionResponse, PreparedRequest
from teoria.platform.ontology.contracts.loader import RegistryCatalog


class MappedFragment(BaseModel):
    mapping_id: str
    operation: str
    record_key: str
    record_order: Any = None
    ontology: str
    object_type: str
    role: str
    properties: dict[str, Any]
    semantic_observations: list[dict[str, Any]] = Field(default_factory=list)


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
                        record_order=order,
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
        observed_at: datetime | None = None,
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
                interpretations = defaultdict(list)
                for target, bindings in mapping.bindings.items():
                    target_parts = target.split(".")
                    object_type = ".".join(target_parts[:-1])
                    property_id = target_parts[-1]
                    for binding_index, binding in enumerate(bindings):
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
                        if binding.meaning is not None:
                            value, observation = self._interpret(catalog, mapping_id, target, binding_index,
                                binding, raw, value, record, source_id, operation_id,
                                f'{call}:{record_key_prefix}:{record_index}', observed_at)
                            interpretations[(key, tuple(sorted(binding.qualifiers.items())))].append(observation)
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
                            property_sets.append((combined, qualifier_key))
                    elif base[key]:
                        property_sets.append((dict(base[key]), ()))
                    for properties, qualifier_key in property_sets:
                        results.append(
                            MappedFragment(
                                mapping_id=mapping_id,
                                operation=call,
                                record_key=f"{call}:{record_key_prefix}:{record_index}",
                                record_order=order,
                                ontology=mapping.ontology,
                                object_type=object_type,
                                role=role,
                                properties=properties,
                                semantic_observations=[*interpretations[(key, ())],
                                    *(interpretations[(key,qualifier_key)] if qualifier_key else [])],
                            )
                        )
        return results

    def _interpret(self, catalog, mapping_id, target, index, binding, raw, value, record, source_id, operation_id, record_key, observed_at):
        plan = catalog.mapping_semantics.get((mapping_id,target,index))
        if plan is None or plan['meaning'] != binding.meaning.model_dump(mode='json') or plan['field'] != binding.field or plan['decode'] != binding.decode:
            raise ValueError('verified_mapping_semantics_required')
        meaning = binding.meaning
        checked_on = (observed_at or datetime.now(timezone.utc)).date()
        if ((plan['valid_from'] and checked_on < date.fromisoformat(str(plan['valid_from']))) or
            (plan['valid_to'] and checked_on > date.fromisoformat(str(plan['valid_to'])))):
            raise ValueError('mapping_binding_outside_validity')
        value_type = plan['value_type']
        if plan['source_type'] in {'number','integer'}:
            if isinstance(raw, bool) or not isinstance(raw, (int,float,Decimal)):
                raise ValueError('mapping_source_number_type_mismatch')
            if plan['source_type']=='integer' and (not Decimal(str(raw)).is_finite() or Decimal(str(raw)) != Decimal(str(raw)).to_integral_value()):
                raise ValueError('mapping_source_integer_type_mismatch')
        if value_type in {'number','decimal','integer','int','float','double'}:
            typed = normalize_property_number(value, value_type, meaning.unit)
            projected = Decimal(typed['decimal'])
        elif value_type in {'string','text'} and isinstance(value, str):
            typed = {'kind':'text','text':value}
            projected = value
        else:
            raise ValueError('mapping_value_type_mismatch')
        effective_at = self._resolve_path(record, meaning.effective_at_field) if meaning.effective_at_field else None
        if effective_at is not None and not isinstance(effective_at, str):
            raise ValueError('mapping_effective_time_requires_source_string')
        if effective_at is not None:
            datetime.fromisoformat(effective_at.replace('Z','+00:00'))
        body = {'ontology':meaning.ontology.model_dump(mode='json'), 'concept_id':str(meaning.concept_id),
                'information_kind':meaning.information_kind, 'operator':meaning.operator, 'scope':meaning.scope,
                'value':typed, 'value_raw':raw, 'unit_raw':meaning.unit.source_unit if meaning.unit else None,
                'effective_at':effective_at,
                'source':{'kind':'api','source_id':source_id,'operation_id':operation_id,
                          'field_path':binding.field.split('.',3)[3], 'record_key':record_key,
                          'mapping_id':mapping_id, 'api_field_binding_id':str(meaning.api_field_binding_id),
                          'runtime_property':target.rsplit('.',1)[1],
                          'mapping_checksum':plan['mapping_checksum'],
                          'source_contract_checksum':plan['source_contract_checksum'],
                          'unit_conversion':meaning.unit.model_dump(mode='json') if meaning.unit else None,
                          'contract_version':catalog.sources[source_id].registry.version}}
        body['observation_id'] = hashlib.sha256(json.dumps(body,sort_keys=True,default=str).encode()).hexdigest()
        return projected, body

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
