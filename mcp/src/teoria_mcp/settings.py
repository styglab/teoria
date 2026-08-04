from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEORIA_MCP_", extra="ignore")

    runtime_mode: str = "remote"
    runtime_api_url: str
    runtime_api_token: str
    runtime_timeout_seconds: float = Field(default=150.0, gt=0)


def bootstrap_mcp_settings(*, cwd: Path | None = None) -> MCPSettings:
    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    settings = MCPSettings()
    if settings.runtime_mode != "remote":
        raise ValueError("TEORIA_MCP_RUNTIME_MODE must be 'remote'")
    return settings
