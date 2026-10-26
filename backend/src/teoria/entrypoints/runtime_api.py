"""Runtime FastAPI application factory and process entrypoint."""

from __future__ import annotations
from contextlib import AsyncExitStack, asynccontextmanager
from fastapi import FastAPI
from teoria.settings import Settings
from teoria.features.access_control.policy import PolicyEvaluator
from teoria.features.runtime.capability.runner import CapabilityRunner
from teoria.features.runtime.runtime_router import router
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog
from teoria.entrypoints.composition.runtime import create_runtime_services


def create_runtime_app(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    runner: CapabilityRunner | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
) -> FastAPI:
    services = create_runtime_services(
        settings=settings,
        catalog=catalog,
        runner=runner,
        policy_evaluator=policy_evaluator,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            if services.owned_cache is not None:
                stack.push_async_callback(services.owned_cache.aclose)
            for resource in services.resources:
                await stack.enter_async_context(resource)
            yield

    app = FastAPI(
        title="Teoria Runtime API",
        version="1.0.0",
        root_path=services.settings.runtime_api_root_path,
        lifespan=lifespan,
    )
    app.state.runtime_services = services
    app.include_router(router)
    return app


def app_factory() -> FastAPI:
    return create_runtime_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "teoria.entrypoints.runtime_api:app_factory",
        factory=True,
        host="0.0.0.0",
        port=8000,
    )


if __name__ == "__main__":
    main()
