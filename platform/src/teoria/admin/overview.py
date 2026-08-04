from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.registry.validator import RegistryValidator


def build_registry_overview(catalog: RegistryCatalog) -> dict[str, Any]:
    diagnostics = RegistryValidator().validate(catalog)
    return {
        "counts": {
            "ontologies": len(catalog.ontologies),
            "object_types": sum(len(item.object_types) for item in catalog.ontologies.values()),
            "link_types": sum(len(item.link_types) for item in catalog.ontologies.values()),
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
