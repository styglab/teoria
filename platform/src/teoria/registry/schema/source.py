from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, field_validator
from teoria_provider.schema import (
    Access,
    Authentication,
    Components,
    ErrorDefinition,
    FieldContainer,
    ObjectDefinition,
    Operation,
    Pagination,
    PaginationField,
    Provider,
    ProviderDefinition,
    Request,
    Response,
    ResponseControl,
    ResponseData,
    Specification,
    SuccessCondition,
)

from teoria.registry.schema.common import FieldDefinition, IdentifiedModel, RegistryMetadata, RegistryModel

# Semantic API Sources and ingestion Connectors deliberately share the same
# provider wire contract. The Source name remains as a Platform-facing alias.
SourceDefinition = ProviderDefinition


class DatabaseAccess(RegistryModel):
    engine: Literal["postgresql"]
    connection_env: str

    @field_validator("connection_env")
    @classmethod
    def connection_env_must_be_a_variable_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("connection_env must be an environment variable name")
        return value


class DatabaseRelationDefinition(IdentifiedModel):
    relation: str
    primary_key: list[str] = Field(min_length=1)
    fields: list[FieldDefinition] = Field(min_length=1)

    @field_validator("relation")
    @classmethod
    def relation_must_be_qualified(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", value):
            raise ValueError("relation must use '<schema>.<relation>'")
        return value


class DatabaseSourceDefinition(IdentifiedModel):
    """A governed relational source read directly by the semantic runtime."""

    description: str
    type: Literal["database"]
    access: DatabaseAccess
    relations: list[DatabaseRelationDefinition] = Field(min_length=1)


class SourceRegistry(RegistryModel):
    registry: RegistryMetadata
    source: Annotated[SourceDefinition | DatabaseSourceDefinition, Field(discriminator="type")]
