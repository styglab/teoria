from __future__ import annotations

from teoria.runtime.capability.handlers import CapabilityHandlers
from teoria.domains.company.identity.processor import (
    execute_company_identifier_resolution,
    execute_company_detail_context,
)


def register_processors(handlers: CapabilityHandlers) -> None:
    handlers.register_processor(
        "company_identity.resolve_company_identifiers", execute_company_identifier_resolution,
    )
    handlers.register_processor(
        "company_identity.get_company_detail_context", execute_company_detail_context,
    )
