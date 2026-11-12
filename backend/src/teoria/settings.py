from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEORIA_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    registry_path: Path = Path("backend/contracts/runtime")
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
    admin_metadata_public_read: bool = False
    admin_api_token: str | None = None
    admin_api_actor: str = "system:admin"
    admin_api_roles: str = "metadata_admin,metadata_reviewer,binding_reviewer,ontology_owner"
    admin_oidc_issuer: str | None = None
    admin_oidc_audience: str | None = None
    admin_oidc_jwks_url: str | None = None
    admin_oidc_roles_claim: str = "roles"
    admin_oidc_role_mapping: dict[str, list[str]] = Field(default_factory=dict)
    admin_data_database_url: str | None = None
    app_database_url: str | None = None
    specification_upload_enabled: bool = False
    specification_authoring_api_token: SecretStr | None = None
    # Kubernetes sets platform/domain activation explicitly; direct API callers retain defaults.
    semantic_modeling_enabled: bool = True
    goods_authoring_enabled: bool | None = None

    formatid_enabled: bool = True
    legal_information_enabled: bool = True
    image_registry_provider: Literal["distribution", "harbor"] = "distribution"
    image_registry_project: str = "models"
    image_registry_url: str = ""
    image_registry_public_host: str = ""
    image_registry_username: str = ""
    image_registry_password: str = ""
    image_registry_ca_pem: str = ""
    model_operations_enabled: bool = False
    model_prefect_url: str = "http://prefect-server:4200/api"
    model_prefect_auth: str = ""
    model_mlflow_url: str = "http://mlflow:5000/mlflow"
    assessment_law_max_documents: int = Field(default=5, ge=1, le=5)
    assessment_law_max_chars: int = Field(default=12000, ge=1000, le=12000)
    assessment_enabled: bool = False
    assessment_codex_model: str | None = None
    assessment_codex_timeout_seconds: int = Field(default=180, ge=1, le=360)
    openmetadata_enabled: bool = False
    openmetadata_base_url: str = "http://localhost:8585/api"
    openmetadata_public_url: str = ""
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
    goods_runtime_view_path: Path | None = None
    goods_runtime_view_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    runtime_artifact_path: Path | None = None
    runtime_artifact_store: Path | None = None

    @field_validator("openmetadata_public_url")
    @classmethod
    def public_console_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        try:
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("public console URL requires HTTP(S), without credentials, query or fragment")
        return value.rstrip("/")

    @property
    def metadata_enabled(self) -> bool:
        return self.semantic_modeling_enabled

    @property
    def ontology_enabled(self) -> bool:
        return self.semantic_modeling_enabled

    @property
    def goods_authoring_active(self) -> bool:
        if self.goods_authoring_enabled is not None:
            return self.goods_authoring_enabled
        return self.formatid_enabled or self.semantic_modeling_enabled

    @field_validator("goods_runtime_view_path", "goods_runtime_view_sha256", mode="before")
    @classmethod
    def optional_goods_runtime_view(cls, value):
        return None if value == "" else value


def bootstrap_settings(*, cwd: Path | None = None) -> Settings:
    """Load one explicit local env file, then validate all Teoria settings."""

    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    return Settings()
