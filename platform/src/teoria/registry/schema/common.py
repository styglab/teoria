from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class RegistryModel(BaseModel):
    """Base model that rejects unknown keys in authored registries."""

    model_config = ConfigDict(extra="forbid")


class RegistryMetadata(RegistryModel):
    version: str
    registered_at: date


class IdentifiedModel(RegistryModel):
    id: str
    name: str | None = None

    @field_validator("id")
    @classmethod
    def id_must_be_snake_case(cls, value: str) -> str:
        if not SNAKE_CASE_PATTERN.fullmatch(value):
            raise ValueError("registry id must be snake_case")
        return value


class ValueDefinition(RegistryModel):
    value: str
    label: str | None = None


from teoria_provider.schema import FieldDefinition  # noqa: E402
