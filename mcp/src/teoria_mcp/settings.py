from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEORIA_MCP_", extra="ignore")

    runtime_mode: Literal["embedded", "remote"] = "embedded"
    runtime_api_url: str | None = None
    embedded_registry_path: Path = Path("platform/registries")
    embedded_source_timeout_seconds: float = Field(default=15.0, gt=0)
    embedded_source_max_attempts: int = Field(default=3, ge=1, le=10)
    embedded_source_max_pages: int = Field(default=100, ge=1, le=10_000)
    embedded_capability_timeout_seconds: float = Field(default=120.0, gt=0)


def bootstrap_mcp_settings(*, cwd: Path | None = None) -> MCPSettings:
    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    if "TEORIA_MCP_EMBEDDED_REGISTRY_PATH" not in os.environ and os.environ.get("TEORIA_REGISTRY_PATH"):
        return MCPSettings(embedded_registry_path=Path(os.environ["TEORIA_REGISTRY_PATH"]))
    return MCPSettings()
