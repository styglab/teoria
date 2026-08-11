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
    source_max_attempts: int = Field(default=2, ge=1, le=10)
    source_retry_backoff_seconds: float = Field(default=60.0, ge=0)
    data_database_url: str | None = None
    object_storage_endpoint: str | None = Field(
        default=None, validation_alias="TEORIA_OBJECT_STORAGE_ENDPOINT"
    )
    object_storage_bucket: str = Field(
        default="teoria", validation_alias="TEORIA_OBJECT_STORAGE_BUCKET"
    )
    object_storage_access_key: str | None = Field(
        default=None, validation_alias="TEORIA_OBJECT_STORAGE_ACCESS_KEY"
    )
    object_storage_secret_key: str | None = Field(
        default=None, validation_alias="TEORIA_OBJECT_STORAGE_SECRET_KEY"
    )
    bid_document_max_bytes: int = Field(default=104857600, gt=0)
    bid_document_max_attempts: int = Field(default=3, ge=1, le=20)
    bid_document_parse_max_attempts: int = Field(default=3, ge=1, le=20)
    bid_eligibility_input_max_chars: int = Field(default=120000, ge=10000, le=500000)
    bid_document_retention_days: int = Field(default=90, ge=1)
    bid_document_purge_batch_size: int = Field(default=500, ge=1, le=5000)


def bootstrap_pipeline_settings(*, cwd: Path | None = None) -> PipelineSettings:
    working_directory = (cwd or Path.cwd()).resolve()
    configured_env_file = os.environ.get("TEORIA_ENV_FILE")
    environment = os.environ.get("TEORIA_ENVIRONMENT", "development")
    env_file = Path(configured_env_file).expanduser() if configured_env_file else working_directory / ".env"
    if configured_env_file or environment != "production":
        load_dotenv(dotenv_path=env_file, override=False)
    return PipelineSettings()
