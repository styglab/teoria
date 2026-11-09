from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from itertools import product
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from teoria.features.semantic_modeling.ontology.observations import SemanticObservation

from teoria.features.runtime.mapping.decoder import MappedFragment
from teoria.features.runtime.provenance import Provenance
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog


class MaterializedObject(BaseModel):
    ontology: str
    object_type: str
    object_id: str
    properties: dict[str, Any]
    provenance: list[Provenance]
    property_provenance: dict[str, list[Provenance]]
    semantic_observations: list[SemanticObservation] = Field(default_factory=list)
    semantic_conflicts: dict[str, str] = Field(default_factory=dict)


class MaterializedLink(BaseModel):
    ontology: str
    link_type: str
    source_object_id: str
    target_object_id: str
    provenance: list[Provenance]


class OntologyMaterializer:
    def materialize(
        self,
        catalog: RegistryCatalog,
        fragments: list[MappedFragment],
        observed_at: datetime,
        allowed_objects: set[str],
        allowed_links: set[str],
    ) -> tuple[list[MaterializedObject], list[MaterializedLink]]:
        objects: dict[str, MaterializedObject] = {}
        object_order: dict[str, tuple] = {}
        links: dict[tuple[str, str, str], MaterializedLink] = {}
        by_operation: dict[tuple[str, str], list[MappedFragment]] = defaultdict(list)
        for fragment in fragments:
            by_operation[(fragment.mapping_id, fragment.operation)].append(fragment)

        for (mapping_id, operation), operation_fragments in by_operation.items():
            mapping = catalog.mappings[mapping_id]
            definition = mapping.materializations[operation]
            by_record: dict[str, list[MappedFragment]] = defaultdict(list)
            for fragment in operation_fragments:
                by_record[fragment.record_key].append(fragment)
            for record_fragments in by_record.values():
                record_instances: dict[str, list[str]] = defaultdict(list)
                for role, spec in definition.objects.items():
                    object_ontology, object_type = (
                        spec.type.split(".", 1)
                        if "." in spec.type
                        else (mapping.ontology, spec.type)
                    )
                    candidates = [fragment for fragment in record_fragments if fragment.role == role]
                    for candidate in candidates:
                        properties = dict(candidate.properties)
                        provenance = self._provenance(candidate, observed_at)
                        execution_provenance = self._execution_provenance(candidate.mapping_id, observed_at)
                        generated_properties: set[str] = set()
                        for timestamp_property in spec.timestamp_properties:
                            properties[timestamp_property] = observed_at
                            generated_properties.add(timestamp_property)
                        parent_lists = [record_instances[parent] for parent in spec.parents]
                        if any(not values for values in parent_lists):
                            continue
                        parent_combinations = product(*parent_lists) if parent_lists else [()]
                        for parent_ids in parent_combinations:
                            identity = {name: properties.get(name) for name in spec.identity}
                            if any(value is None or value == "" for value in identity.values()):
                                continue
                            identity["parents"] = list(parent_ids)
                            object_id = self._id(object_ontology, object_type, identity)
                            if spec.id_property:
                                properties[spec.id_property] = object_id
                                generated_properties.add(spec.id_property)
                            property_provenance = {
                                key: [execution_provenance if key in generated_properties else provenance]
                                for key in properties
                            }
                            current = objects.get(object_id)
                            order = self._order_key(candidate.record_order)
                            if current is None:
                                objects[object_id] = MaterializedObject(
                                    ontology=object_ontology,
                                    object_type=object_type,
                                    object_id=object_id,
                                    properties=dict(properties),
                                    provenance=[provenance, execution_provenance] if generated_properties else [provenance],
                                    property_provenance=property_provenance,
                                )
                                object_order[object_id] = order
                            elif order >= object_order[object_id]:
                                updates = {key: value for key, value in properties.items() if value is not None and value != ""}
                                current.properties.update(updates)
                                for key in updates:
                                    current.property_provenance[key] = property_provenance[key]
                                self._append_provenance(current.provenance, provenance)
                                if generated_properties:
                                    self._append_provenance(current.provenance, execution_provenance)
                                object_order[object_id] = order
                            else:
                                for key, value in properties.items():
                                    if key not in current.properties and value is not None and value != "":
                                        current.properties[key] = value
                                        current.property_provenance[key] = property_provenance[key]
                                self._append_provenance(current.provenance, provenance)
                                if generated_properties:
                                    self._append_provenance(current.provenance, execution_provenance)
                            for body in candidate.semantic_observations:
                                observation = SemanticObservation.model_validate({**body,
                                    'subject_refs':[object_id], 'observed_at':observed_at})
                                current_object = objects[object_id]
                                if not any(o.observation_id == observation.observation_id for o in current_object.semantic_observations):
                                    current_object.semantic_observations.append(observation)
                            record_instances[role].append(object_id)

                for link in definition.links:
                    for source_id, target_id in product(record_instances[link.source], record_instances[link.target]):
                        key = (link.type, source_id, target_id)
                        provenance = self._provenance(record_fragments[0], observed_at)
                        if key not in links:
                            links[key] = MaterializedLink(
                                ontology=mapping.ontology,
                                link_type=link.type,
                                source_object_id=source_id,
                                target_object_id=target_id,
                                provenance=[provenance],
                            )
                        else:
                            self._append_provenance(links[key].provenance, provenance)

        for obj in objects.values():
            values = defaultdict(set)
            for observation in obj.semantic_observations:
                property_id = observation.source.get('runtime_property')
                if property_id is None:
                    continue
                value = dict(observation.value)
                if value.get('kind') == 'number':
                    value['decimal'] = str(Decimal(value['decimal']).normalize())
                values[property_id].add(json.dumps([str(observation.concept_id),
                    observation.ontology.model_dump(mode='json'), observation.information_kind,
                    observation.operator, observation.scope, observation.effective_at, observation.conditions, value],
                    sort_keys=True, default=str))
            for property_id, interpretations in values.items():
                if len(interpretations) > 1:
                    obj.semantic_conflicts[property_id] = 'multiple_observations_require_review'
                    obj.properties.pop(property_id, None)
                    obj.property_provenance.pop(property_id, None)
        return (
            [item for item in objects.values() if f"{item.ontology}.{item.object_type}" in allowed_objects],
            [item for item in links.values() if f"{item.ontology}.{item.link_type}" in allowed_links],
        )

    @staticmethod
    def _order_key(value: Any) -> tuple:
        if value is None:
            return (0, "")
        if isinstance(value, bool):
            raise ValueError("record order cannot be boolean")
        if isinstance(value, (int, float, Decimal)):
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError("record order must be finite")
            return (1, number)
        if isinstance(value, datetime):
            return (2, value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp())
        if isinstance(value, date):
            return (2, datetime.combine(value, datetime.min.time(), timezone.utc).timestamp())
        if isinstance(value, str):
            return (3, value)
        raise ValueError("record order must be a number, date or string")

    @staticmethod
    def _id(ontology: str, object_type: str, identity: dict[str, Any]) -> str:
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(f"{ontology}:{object_type}:{canonical}".encode()).hexdigest()

    @staticmethod
    def _provenance(fragment: MappedFragment, observed_at: datetime) -> Provenance:
        source, operation = fragment.operation.split(".", 1)
        return Provenance(
            kind="source",
            source=source,
            operation=operation,
            mapping=fragment.mapping_id,
            observed_at=observed_at,
            record_keys=[fragment.record_key],
        )

    @staticmethod
    def _execution_provenance(mapping_id: str, observed_at: datetime) -> Provenance:
        return Provenance(
            kind="execution",
            source="teoria",
            operation="materialize",
            mapping=mapping_id,
            observed_at=observed_at,
            record_keys=[],
        )

    @staticmethod
    def _append_provenance(items: list[Provenance], value: Provenance) -> None:
        existing = next(
            (
                item
                for item in items
                if item.source == value.source
                and item.kind == value.kind
                and item.operation == value.operation
                and item.mapping == value.mapping
                and item.observed_at == value.observed_at
            ),
            None,
        )
        if existing is None:
            items.append(value)
        else:
            existing.record_keys.extend(key for key in value.record_keys if key not in existing.record_keys)
