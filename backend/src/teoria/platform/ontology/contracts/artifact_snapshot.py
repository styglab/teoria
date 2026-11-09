"""Select approved bindings whose targets remain in this Runtime release."""

from typing import Any
from teoria.platform.ontology.contracts.loader import RegistryCatalog


def select_registry_bindings(
    catalog: RegistryCatalog,
    bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Omit targets retired from this release without changing authoring history.

    Retained targets still undergo the compiler's version and compatibility
    checks. In particular, this never rewrites an approved target's version.
    """
    return [
        item
        for item in bindings
        if (
            not str(item.get("target_type", "")).startswith("capability")
            or item.get("capability_id") in catalog.capabilities
        )
        and (
            item.get("target_type") != "api_field"
            or item.get("api_source_id") in catalog.sources
        )
    ]
