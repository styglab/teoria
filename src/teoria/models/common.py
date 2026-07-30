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


class FieldDefinition(RegistryModel):
    """A source field. Its id intentionally preserves the provider's spelling."""

    id: str | None = None
    name: str | None = None
    type: Literal["object", "array"] | None = None
    data_type: str | None = None
    ref: str | None = None
    default: Any = None
    max_items: int | None = Field(default=None, gt=0)
    fields: list[FieldDefinition] = Field(default_factory=list)
    items: FieldDefinition | None = None
    values: list[ValueDefinition] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "FieldDefinition":
        declared_shapes = sum(value is not None for value in (self.type, self.data_type, self.ref))
        if declared_shapes != 1:
            raise ValueError("field must declare exactly one of type, data_type, or ref")
        if self.ref and self.fields:
            raise ValueError("ref cannot be combined with fields")
        if self.type == "array" and self.items is None:
            raise ValueError("array field must declare items")
        if self.type != "array" and self.items is not None:
            raise ValueError("items is only valid for an array field")
        if self.type != "array" and self.max_items is not None:
            raise ValueError("max_items is only valid for an array field")
        if self.type != "object" and self.fields:
            raise ValueError("nested fields are only valid for an object field")
        if self.type == "object" and not self.fields:
            raise ValueError("object field must declare fields")
        if self.required and self.type != "object" and self.ref is None:
            raise ValueError("required is only valid for an object or ref field")
        return self
