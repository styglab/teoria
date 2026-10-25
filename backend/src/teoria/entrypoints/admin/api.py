from __future__ import annotations

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from teoria.entrypoints.admin.composition import create_admin_services, install_admin_routers
from teoria.features.access_control.auth import AdminPrincipal
from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.settings import Settings
from teoria.features.runtime.context import ContextEngine
from teoria.features.metadata_management.intelligence.suggestions.repository import SuggestionRepository
from teoria.integrations.openmetadata import OpenMetadataService
from teoria.features.access_control.policy import PolicyEvaluator
from teoria.features.semantic_modeling.registry.loader import RegistryCatalog


def create_admin_app(
    *,
    settings: Settings | None = None,
    catalog: RegistryCatalog | None = None,
    metadata_service: OpenMetadataService | None = None,
    binding_repository: BindingRepository | None = None,
    suggestion_repository: SuggestionRepository | None = None,
    context_engine: ContextEngine | None = None,
    policy_evaluator: PolicyEvaluator | None = None,
) -> FastAPI:
    services = create_admin_services(
        settings=settings,
        catalog=catalog,
        metadata_service=metadata_service,
        binding_repository=binding_repository,
        suggestion_repository=suggestion_repository,
        context_engine=context_engine,
        policy_evaluator=policy_evaluator,
    )
    app = FastAPI(
        title="Teoria Admin API",
        version="1.0.0",
        root_path=services.settings.admin_api_root_path,
    )
    if services.settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["*"],
        )
    install_admin_routers(app, services)

    @app.get("/v1/admin/auth/session", tags=["authentication"])
    async def session(response: Response,
                      principal: AdminPrincipal = Depends(services.authorizer.require())) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return {"actor": principal.actor, "roles": sorted(principal.roles)}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def app_factory() -> FastAPI:
    return create_admin_app()
