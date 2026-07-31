from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from itertools import product
from typing import Any

from pydantic import BaseModel

from teoria.runtime.mapping.decoder import MappedFragment
from teoria.runtime.provenance import Provenance
from teoria.registry.loader import RegistryCatalog


class MaterializedObject(BaseModel):
    ontology: str
    object_type: str
    object_id: str
    properties: dict[str, Any]
    provenance: list[Provenance]
    property_provenance: dict[str, list[Provenance]]


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
        object_order: dict[str, str] = {}
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
                            object_id = self._id(mapping.ontology, spec.type, identity)
                            if spec.id_property:
                                properties[spec.id_property] = object_id
                                generated_properties.add(spec.id_property)
                            property_provenance = {
                                key: [execution_provenance if key in generated_properties else provenance]
                                for key in properties
                            }
                            current = objects.get(object_id)
                            order = candidate.record_order or ""
                            if current is None:
                                objects[object_id] = MaterializedObject(
                                    ontology=mapping.ontology,
                                    object_type=spec.type,
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

        return (
            [item for item in objects.values() if item.object_type in allowed_objects],
            [item for item in links.values() if item.link_type in allowed_links],
        )

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
