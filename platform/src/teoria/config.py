from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEORIA_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    registry_path: Path = Path("platform/registries")
    log_level: str = "INFO"
    source_timeout_seconds: float = Field(default=15.0, gt=0)
    source_max_attempts: int = Field(default=3, ge=1, le=10)
    source_max_pages: int = Field(default=100, ge=1, le=10_000)
    capability_timeout_seconds: float = Field(default=120.0, gt=0)
    runtime_api_token: str | None = None
    runtime_api_root_path: str = ""
    runtime_cache_backend: Literal["memory", "redis", "disabled"] = "memory"
    runtime_cache_url: str = "redis://localhost:6379/0"
    runtime_cache_prefix: str = "teoria:runtime"
    admin_api_root_path: str = ""
    admin_auth_mode: Literal["disabled", "bearer"] = "disabled"
    admin_api_token: str | None = None
    admin_api_actor: str = "system:admin"
    admin_api_roles: str = "metadata_admin,metadata_reviewer,binding_reviewer,ontology_owner"
    admin_data_database_url: str | None = None
    app_database_url: str | None = None
    openmetadata_enabled: bool = False
    openmetadata_base_url: str = "http://localhost:8585/api"
    openmetadata_auth_token: str | None = None
    openmetadata_timeout_seconds: float = Field(default=10.0, gt=0)
    openmetadata_verify_ssl: bool = True
    openmetadata_database_service: str = "teoria_postgresql"
    context_runtime_api_url: str = "http://localhost:8000"
    context_runtime_api_token: str | None = None
    context_runtime_timeout_seconds: float = Field(default=150.0, gt=0)
    context_max_period_years: int = Field(default=10, ge=1, le=100)
    context_max_pages: int = Field(default=100, ge=1, le=10_000)
    policy_mode: Literal["disabled", "opa"] = "disabled"
    opa_url: str = "http://localhost:8181"
    opa_decision_path: str = "teoria/authz/decision"
    opa_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    opa_control_plane_token: str | None = None
    opa_bundle_path: Path = Path("/var/lib/teoria/opa/teoria.tar.gz")
    registry_require_published: bool = False
    runtime_artifact_path: Path | None = None
    runtime_artifact_store: Path | None = None


def bootstrap_settings(*, cwd: Path | None = None) -> Settings:
    """Load one explicit local env file, then validate all Teoria settings."""

    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    return Settings()
