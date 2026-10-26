from __future__ import annotations

from teoria.settings import Settings, bootstrap_settings
from teoria.features.runtime.services import RuntimeServices
from teoria.features.runtime.capability.runner import CapabilityRunner
from teoria.features.runtime.cache import create_runtime_cache
from teoria.features.access_control.policy import (
    PolicyEvaluator,
    OpaPolicyEvaluator,
    create_policy_evaluator,
)
from teoria.features.semantic_modeling.registry.loader import (
    RegistryCatalog,
    RegistryLoader,
)
from teoria.features.semantic_modeling.registry.artifact import (
    RuntimeBundleLoader,
    RegistryArtifactStore,
)
from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.secrets import EnvironmentSecretProvider


def create_runtime_services(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    runner: CapabilityRunner | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
) -> RuntimeServices:
    resolved_settings = settings or bootstrap_settings()
    resources = []
    if not resolved_settings.runtime_api_token:
        raise RuntimeError("TEORIA_RUNTIME_API_TOKEN is required")
    runtime_bundle = None
    if catalog is not None:
        resolved_catalog = catalog
    elif resolved_settings.runtime_artifact_path is not None:
        loaded_bundle = RuntimeBundleLoader(
            resolved_settings.runtime_artifact_path
        ).load()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
    elif resolved_settings.runtime_artifact_store is not None:
        loaded_bundle = RegistryArtifactStore(
            resolved_settings.runtime_artifact_store
        ).load_active()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
    elif resolved_settings.environment == "production":
        raise RuntimeError(
            "TEORIA_RUNTIME_ARTIFACT_PATH or TEORIA_RUNTIME_ARTIFACT_STORE "
            "is required in production"
        )
    else:
        resolved_catalog = RegistryLoader(resolved_settings.registry_path).load()
    if resolved_settings.registry_require_published and (
        resolved_catalog.release is None
        or resolved_catalog.release.status != "published"
    ):
        raise RuntimeError("a published, checksum-valid Registry release is required")
    from teoria.features.goods_querying.capabilities import register_server_capabilities
    from teoria.features.runtime.composition import create_capability_handlers

    handlers = create_capability_handlers()
    register_server_capabilities(handlers)
    resolved_runner = runner or CapabilityRunner(
        ProviderExecutor(
            timeout_seconds=resolved_settings.source_timeout_seconds,
            max_attempts=resolved_settings.source_max_attempts,
            secret_provider=EnvironmentSecretProvider(),
        ),
        handlers=handlers,
        timeout_seconds=resolved_settings.capability_timeout_seconds,
        max_pages=resolved_settings.source_max_pages,
        cache=create_runtime_cache(
            resolved_settings.runtime_cache_backend,
            url=resolved_settings.runtime_cache_url,
            prefix=resolved_settings.runtime_cache_prefix,
        ),
    )
    resolved_policy_evaluator = policy_evaluator or create_policy_evaluator(
        resolved_settings
    )
    if runner is None:
        resources.append(resolved_runner.executor)
    if policy_evaluator is None and isinstance(
        resolved_policy_evaluator, OpaPolicyEvaluator
    ):
        resources.append(resolved_policy_evaluator)
    return RuntimeServices(
        settings=resolved_settings,
        catalog=resolved_catalog,
        runner=resolved_runner,
        policy_evaluator=resolved_policy_evaluator,
        bundle=runtime_bundle,
        resources=resources,
        owned_cache=resolved_runner.cache if runner is None else None,
    )
