"""Runtime dependencies shared by its HTTP handlers; assembled by the process entrypoint."""

from dataclasses import dataclass, field
from typing import Any

from teoria.settings import Settings
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog
from teoria.features.semantic_modeling.registry.artifact import RuntimeBundleManifest
from teoria.features.runtime.capability.runner import CapabilityRunner
from teoria.features.access_control.policy import PolicyEvaluator


@dataclass
class RuntimeServices:
    settings: Settings
    catalog: RegistryCatalog
    runner: CapabilityRunner
    policy_evaluator: PolicyEvaluator
    bundle: RuntimeBundleManifest | None = None
    resources: list[Any] = field(default_factory=list)
    owned_cache: Any | None = None
