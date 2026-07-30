from __future__ import annotations

from datetime import date

from pydantic import Field, HttpUrl, field_validator

from teoria.registry.schema.common import RegistryModel, SNAKE_CASE_PATTERN


class ReferenceFile(RegistryModel):
    path: str
    media_type: str

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        if not value or value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("reference file path must be a safe relative path")
        return value


class ProviderReference(RegistryModel):
    provider: str
    source: str
    title: str
    retrieved_at: date
    official_url: HttpUrl | None = None
    files: list[ReferenceFile] = Field(min_length=1)
    registry: str

    @field_validator("source")
    @classmethod
    def source_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("reference source must be snake_case")
        return value

    @field_validator("registry")
    @classmethod
    def registry_path_must_be_relative(cls, value: str) -> str:
        if not value or value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("reference registry must be a safe relative path")
        return value
