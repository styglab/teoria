import re
from typing import Literal

from pydantic import Field, field_validator

from teoria.registry.schema.common import IdentifiedModel, RegistryMetadata, RegistryModel


class DataTypeDefinition(IdentifiedModel):
    base_type: Literal["string", "integer", "number", "boolean"]
    pattern: str | None = None
    normalization: list[str] = Field(default_factory=list)

    @field_validator("pattern")
    @classmethod
    def pattern_must_compile(cls, value: str | None) -> str | None:
        if value is not None:
            re.compile(value)
        return value


class DataTypeRegistry(RegistryModel):
    registry: RegistryMetadata
    data_types: list[DataTypeDefinition]
