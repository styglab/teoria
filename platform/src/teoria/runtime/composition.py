"""Compose active domain handlers without loading retired procurement services."""

from teoria.runtime.capability.handlers import CapabilityHandlers


def create_capability_handlers() -> CapabilityHandlers:
    # Declarative Source/Mapping queries use the common runner directly. Register
    # a processor here only when its active domain implementation exists.
    return CapabilityHandlers()
