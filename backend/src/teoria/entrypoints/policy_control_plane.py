"""OPA control-plane FastAPI factory and process entrypoint."""

from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from teoria.settings import Settings, bootstrap_settings
from teoria.features.access_control.policy.telemetry_repository import (
    PolicyTelemetryRepository,
    PostgresPolicyTelemetryRepository,
)
from teoria.features.access_control.policy.control_plane_router import (
    create_policy_control_plane_router,
)


def create_policy_control_plane_app(
    *,
    settings: Settings | None = None,
    repository: PolicyTelemetryRepository | None = None,
) -> FastAPI:
    resolved = settings or bootstrap_settings()
    if not resolved.opa_control_plane_token:
        raise RuntimeError("TEORIA_OPA_CONTROL_PLANE_TOKEN is required")
    if repository is None:
        if not resolved.app_database_url:
            raise RuntimeError("TEORIA_APP_DATABASE_URL is required")
        repository = PostgresPolicyTelemetryRepository(resolved.app_database_url)
    app = FastAPI(title="Teoria OPA Control Plane", version="1.0.0")
    app.include_router(
        create_policy_control_plane_router(
            token=resolved.opa_control_plane_token,
            bundle_path=Path(resolved.opa_bundle_path),
            repository=repository,
        )
    )
    return app


def app_factory() -> FastAPI:
    return create_policy_control_plane_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "teoria.entrypoints.policy_control_plane:app_factory",
        factory=True,
        host="0.0.0.0",
        port=8002,
    )


if __name__ == "__main__":
    main()
