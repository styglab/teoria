from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog


def validate_capability_compatibility(
    catalog: RegistryCatalog,
    ontologies: list[dict[str, Any]],
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
        reports.append({
            "capability_id": capability_id,
            "capability_version": capability.version,
            "definition_checksum": catalog.capability_checksums[(capability_id, capability.version)],
            "status": "incompatible" if missing_required else "compatible",
            "semantic_requirements_declared": declared_count > 0,
            "resolved": resolved,
            "missing_required": missing_required,
            "unresolved_optional": unresolved_optional,
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
        }
