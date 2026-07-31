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


def bootstrap_settings(*, cwd: Path | None = None) -> Settings:
    """Load one explicit local env file, then validate all Teoria settings."""

    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    # Temporary compatibility for the pre-Settings variable name.
    legacy_registry_path = os.environ.get("TEORIA_REGISTRIES")
    if "TEORIA_REGISTRY_PATH" not in os.environ and legacy_registry_path:
        return Settings(registry_path=Path(legacy_registry_path))
    return Settings()
