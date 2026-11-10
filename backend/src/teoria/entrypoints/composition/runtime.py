from __future__ import annotations

from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.secrets import EnvironmentSecretProvider
from teoria.platform.access_control.policy import (
    OpaPolicyEvaluator,
    PolicyEvaluator,
    create_policy_evaluator,
)
from teoria.platform.ontology.contracts.artifact import (
    RegistryArtifactStore,
    RuntimeBundleLoader,
)
from teoria.platform.ontology.contracts.loader import (
    RegistryCatalog,
    RegistryLoader,
)
from teoria.platform.ontology.runtime.cache import create_runtime_cache
from teoria.platform.ontology.runtime.capability.runner import CapabilityRunner
from teoria.platform.ontology.runtime.dependencies import RuntimeServices
from teoria.settings import Settings, bootstrap_settings


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
    published_ontologies = []
    if catalog is not None:
        resolved_catalog = catalog
    elif resolved_settings.runtime_artifact_path is not None:
        loaded_bundle = RuntimeBundleLoader(
            resolved_settings.runtime_artifact_path
        ).load()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
        published_ontologies = loaded_bundle.ontologies
    elif resolved_settings.runtime_artifact_store is not None:
        loaded_bundle = RegistryArtifactStore(
            resolved_settings.runtime_artifact_store
        ).load_active()
        resolved_catalog = loaded_bundle.catalog
        runtime_bundle = loaded_bundle.manifest
        published_ontologies = loaded_bundle.ontologies
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
    from teoria.platform.ontology.runtime.capability.handlers import CapabilityHandlers

    handlers = CapabilityHandlers()
    goods_query = resolved_catalog.capabilities.get("get_goods_document_requirements")
    if goods_query is not None and not resolved_settings.goods_runtime_view_path:
        raise RuntimeError("active goods requirements query requires a pinned view")
    if (
        resolved_settings.goods_runtime_view_path is not None
        or resolved_settings.goods_runtime_view_sha256
    ):
        if runner is not None:
            raise RuntimeError(
                "configured goods view cannot be bypassed by an injected runner"
            )
        if (
            runtime_bundle is None
            or resolved_settings.goods_runtime_view_path is None
            or not resolved_settings.goods_runtime_view_sha256
        ):
            raise RuntimeError(
                "goods Runtime requires a verified bundle, view path and SHA256"
            )
        from teoria.domains.goods.runtime import (
            PROCESSOR_ID,
            load_requirements_view,
            requirements_handler,
        )

        view = load_requirements_view(
            resolved_settings.goods_runtime_view_path,
            resolved_settings.goods_runtime_view_sha256,
            published_ontologies,
        )
        handlers.register_processor(PROCESSOR_ID, requirements_handler(view))
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
