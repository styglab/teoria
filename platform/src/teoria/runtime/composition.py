from teoria.domains.company.processors import register_processors as register_company
from teoria.domains.public_procurement.processors import register_processors as register_procurement
from teoria.runtime.capability.handlers import CapabilityHandlers


def create_capability_handlers() -> CapabilityHandlers:
    handlers = CapabilityHandlers()
    register_company(handlers)
    register_procurement(handlers)
    return handlers
