from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog


def validate_capability_compatibility(
    catalog: RegistryCatalog,
    ontologies: list[dict[str, Any]],
    bindings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    semantic_resources: dict[str, dict[str, Any]] = {}
    for artifact in ontologies:
        content = artifact.get("content") or {}
        for item in content.get("objects", []):
            _index_resource(semantic_resources, item, "concept")
            for prop in item.get("properties", []):
                _index_resource(semantic_resources, prop, "property")
        for item in content.get("relationships", []):
            _index_resource(semantic_resources, item, "relationship")

    reports = []
    for capability_id, capability in sorted(catalog.capabilities.items()):
        missing_required = []
        unresolved_optional = []
        resolved = []
        type_mismatches = []
        groups = (
            ("concept", capability.semantic_requirements.concepts),
            ("property", capability.semantic_requirements.properties),
            ("relationship", capability.semantic_requirements.relationships),
        )
        for expected_kind, requirements in groups:
            for requirement in requirements:
                resource = semantic_resources.get(requirement.stable_key)
                matches = resource is not None and resource["kind"] == expected_kind
                if matches and requirement.semantic_id is not None:
                    matches = str(resource.get("concept_id")) == str(requirement.semantic_id)
                if matches:
                    resolved.append({
                        "kind": expected_kind,
                        "stable_key": requirement.stable_key,
                        "semantic_id": resource.get("concept_id"),
                    })
                elif requirement.required:
                    missing_required.append({
                        "kind": expected_kind,
                        "stable_key": requirement.stable_key,
                        "semantic_id": str(requirement.semantic_id) if requirement.semantic_id else None,
                    })
                else:
                    unresolved_optional.append({
                        "kind": expected_kind,
                        "stable_key": requirement.stable_key,
                    })
        declared_count = sum(len(items) for _, items in groups)
        for binding in bindings or []:
            if binding.get("capability_id") != capability_id:
                continue
            scope = binding.get("capability_target_scope") or binding.get("target_scope")
            field_path = binding.get("capability_field_path") or binding.get("field_path")
            if scope != "input" or field_path not in capability.inputs:
                continue
            semantic = semantic_resources.get(str(binding.get("ontology_stable_key")))
            if semantic is None or semantic["kind"] != "property":
                continue
            capability_input = capability.inputs[field_path]
            actual_type = _capability_input_base_type(catalog, capability_input)
            expected_type = _semantic_base_type(semantic.get("value_type"))
            actual_collection = capability_input.collection
            expected_collection = (
                "list" if semantic.get("cardinality") == "many" else "scalar"
            )
            if (
                actual_type is not None
                and expected_type is not None
                and actual_type != expected_type
            ) or actual_collection != expected_collection:
                type_mismatches.append({
                    "field_path": field_path,
                    "stable_key": binding.get("ontology_stable_key"),
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "expected_collection": expected_collection,
                    "actual_collection": actual_collection,
                })
        reports.append({
            "capability_id": capability_id,
            "capability_version": capability.version,
            "definition_checksum": catalog.capability_checksums[(capability_id, capability.version)],
            "status": (
                "incompatible" if missing_required or type_mismatches else "compatible"
            ),
            "semantic_requirements_declared": declared_count > 0,
            "resolved": resolved,
            "missing_required": missing_required,
            "unresolved_optional": unresolved_optional,
            "type_mismatches": type_mismatches,
        })
    return reports


def _index_resource(
    target: dict[str, dict[str, Any]], item: dict[str, Any], kind: str,
) -> None:
    stable_key = item.get("stable_key")
    if stable_key:
        target[str(stable_key)] = {
            "kind": kind,
            "concept_id": item.get("concept_id"),
            "value_type": item.get("value_type"),
            "cardinality": item.get("cardinality"),
            "unit": item.get("unit"),
        }


def _semantic_base_type(value_type: Any) -> str | None:
    if not value_type:
        return None
    return {
        "decimal": "number",
        "money": "number",
        "float": "number",
        "int": "integer",
    }.get(str(value_type), str(value_type))


def _capability_input_base_type(catalog: RegistryCatalog, capability_input: Any) -> str | None:
    data_type = capability_input.data_type
    if capability_input.property:
        parts = capability_input.property.split(".")
        if len(parts) != 3:
            return None
        contract = catalog.runtime_contracts.get(parts[0])
        if contract is None:
            return None
        object_type = next(
            (item for item in contract.object_types if item.id == parts[1]), None
        )
        if object_type is None:
            return None
        runtime_property = next(
            (item for item in object_type.properties if item.id == parts[2]), None
        )
        if runtime_property is None:
            return None
        if runtime_property.value_set:
            return "string"
        data_type = runtime_property.data_type
    if data_type in catalog.data_types:
        return catalog.data_types[data_type].base_type
    return _semantic_base_type(data_type)
