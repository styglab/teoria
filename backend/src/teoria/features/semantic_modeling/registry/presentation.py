from __future__ import annotations

from typing import Any

from teoria.features.semantic_modeling.registry.loader import RegistryCatalog
from teoria.features.semantic_modeling.registry.composition import (
    create_registry_validator,
)


def build_registry_overview(catalog: RegistryCatalog) -> dict[str, Any]:
    diagnostics = create_registry_validator().validate(catalog)
    owners = set()
    for paths in (
        catalog.runtime_contract_paths,
        catalog.capability_paths,
        catalog.mapping_paths,
    ):
        for path in paths.values():
            relative = path.relative_to(catalog.root)
            if len(relative.parts) > 2 and relative.parts[0] == "domains":
                owners.add(relative.parts[1])
    return {
        "counts": {
            "business_domains": len(owners),
            "runtime_contracts": len(catalog.runtime_contracts),
            "runtime_contract_domains": len(
                catalog.runtime_contracts
            ),  # legacy API key
            "runtime_object_types": sum(
                len(item.object_types) for item in catalog.runtime_contracts.values()
            ),
            "runtime_link_types": sum(
                len(item.link_types) for item in catalog.runtime_contracts.values()
            ),
            "sources": len(catalog.sources),
            "mappings": len(catalog.mappings),
            "capabilities": len(catalog.capabilities),
            "data_types": len(catalog.data_types),
            "value_sets": len(catalog.value_sets),
        },
        "validation": {
            "status": "valid" if not diagnostics else "invalid",
            "diagnostic_count": len(diagnostics),
        },
    }
