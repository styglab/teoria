from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from teoria.registry.schema.common import IdentifiedModel, RegistryMetadata, RegistryModel


TRANSFORM_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+$")


class MappingBinding(RegistryModel):
    field: str | dict[str, str]
    decode: str | None = None
    encode: str | None = None
    qualifiers: dict[str, str] = Field(default_factory=dict)
    role: str | None = None

    @field_validator("decode", "encode")
    @classmethod
    def codec_must_be_callable_path(cls, value: str | None) -> str | None:
        if value is not None and not TRANSFORM_PATTERN.fullmatch(value):
            raise ValueError("codec must use '<module>.<function>'")
        return value

    @model_validator(mode="after")
    def validate_direction(self) -> "MappingBinding":
        if isinstance(self.field, dict) and not self.field:
            raise ValueError("field mapping must not be empty")
        fields = [self.field] if isinstance(self.field, str) else list(self.field.values())
        sections = {reference.split(".")[2] for reference in fields if len(reference.split(".")) >= 3}
        if len(sections) > 1:
            raise ValueError("one binding cannot mix request and response fields")
        if "response" in sections and self.encode:
            raise ValueError("response binding cannot declare encode")
        if "request" in sections and self.decode:
            raise ValueError("request binding cannot declare decode")
        if "request" in sections and self.qualifiers:
            raise ValueError("request binding cannot declare qualifiers")
        return self


class ObjectMaterialization(RegistryModel):
    type: str
    identity: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)
    id_property: str | None = None
    timestamp_properties: list[str] = Field(default_factory=list)
    merge: Literal["latest_non_empty"] = "latest_non_empty"

    @model_validator(mode="after")
    def require_identity_or_parent(self) -> "ObjectMaterialization":
        if not self.identity and not self.parents:
            raise ValueError("materialized object requires identity properties or parent roles")
        return self


class LinkMaterialization(RegistryModel):
    type: str
    source: str
    target: str


class Materialization(RegistryModel):
    record_order: str | None = None
    objects: dict[str, ObjectMaterialization]
    links: list[LinkMaterialization] = Field(default_factory=list)


class MappingDefinition(IdentifiedModel):
    description: str
    ontology: str
    bindings: dict[str, list[MappingBinding]]
    materializations: dict[str, Materialization] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bindings_must_not_be_empty(self) -> "MappingDefinition":
        if not self.bindings:
            raise ValueError("mapping bindings must not be empty")
        if any(not rules for rules in self.bindings.values()):
            raise ValueError("every ontology property must contain at least one field binding")
        return self


class MappingRegistry(RegistryModel):
    registry: RegistryMetadata
    mapping: MappingDefinition
