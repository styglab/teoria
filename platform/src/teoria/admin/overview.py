from __future__ import annotations

from typing import Any

from teoria.registry.loader import RegistryCatalog
from teoria.registry.validator import RegistryValidator


def build_registry_overview(catalog: RegistryCatalog) -> dict[str, Any]:
    diagnostics = RegistryValidator().validate(catalog)
    return {
        "counts": {
            "runtime_contract_domains": len(catalog.runtime_contracts),
            "runtime_object_types": sum(
                len(item.object_types) for item in catalog.runtime_contracts.values()
            ),
            "runtime_link_types": sum(
                len(item.link_types) for item in catalog.runtime_contracts.values()
            ),
            # Compatibility fields retained for one Registry release.
            "ontologies": len(catalog.runtime_contracts),
            "object_types": sum(len(item.object_types) for item in catalog.runtime_contracts.values()),
            "link_types": sum(len(item.link_types) for item in catalog.runtime_contracts.values()),
            "sources": len(catalog.sources),
            "mappings": len(catalog.mappings),
            "capabilities": len(catalog.capabilities),
            "eligibility_rules": len(catalog.eligibility_rules),
            "data_types": len(catalog.data_types),
            "value_sets": len(catalog.value_sets),
        },
        "validation": {
            "status": "valid" if not diagnostics else "invalid",
            "diagnostic_count": len(diagnostics),
        },
    }
