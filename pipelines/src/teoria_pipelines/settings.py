from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEORIA_PIPELINE_", extra="ignore")

    path: Path = Path("pipelines")
    source_timeout_seconds: float = Field(default=30.0, gt=0)
    source_max_attempts: int = Field(default=3, ge=1, le=10)
    data_database_url: str | None = None


def bootstrap_pipeline_settings(*, cwd: Path | None = None) -> PipelineSettings:
    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    return PipelineSettings()
