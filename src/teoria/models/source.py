from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from teoria.models.common import (
    FieldDefinition,
    IdentifiedModel,
    RegistryMetadata,
    RegistryModel,
)


class Provider(RegistryModel):
    organization: str
    distribution: str | None = None


class Specification(RegistryModel):
    format: str
    version: str
    schema_version: str | None = None
    api_version: str | None = None
    source_document: str | None = None


class Authentication(RegistryModel):
    type: Literal["api_key", "basic", "bearer", "none"]
    location: str | None = Field(default=None, alias="in")
    name: str | None = None
    credential_env: str | None = None

    @model_validator(mode="after")
    def validate_api_key(self) -> "Authentication":
        if self.type == "api_key":
            if self.location not in {"query", "header"}:
                raise ValueError("api_key authentication requires in: query or header")
            if not self.name:
                raise ValueError("api_key authentication requires name")
            if not self.credential_env:
                raise ValueError("api_key authentication requires credential_env")
        return self

    @field_validator("credential_env")
    @classmethod
    def credential_env_must_be_a_variable_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("credential_env must be an environment variable name")
        return value


class Access(RegistryModel):
    base_url: str
    authentication: Authentication | None = None

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return value.rstrip("/")


class ObjectDefinition(IdentifiedModel):
    fields: list[FieldDefinition]


class Components(RegistryModel):
    objects: list[ObjectDefinition] = Field(min_length=1)


class FieldContainer(RegistryModel):
    type: Literal["object"] | None = None
    fields: list[FieldDefinition] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)


class Request(RegistryModel):
    content_type: str | None = None
    query: FieldContainer | None = None
    header: FieldContainer | None = None
    body: FieldContainer | None = None


class ResponseData(RegistryModel):
    record_path: str
    ref: str | None = None
    fields: list[FieldDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_one_schema(self) -> "ResponseData":
        if bool(self.ref) == bool(self.fields):
            raise ValueError("response data must declare exactly one of ref or fields")
        return self


class SuccessCondition(RegistryModel):
    field: str
    equals: str


class ResponseControl(FieldContainer):
    record_path: str
    success: SuccessCondition


class Response(RegistryModel):
    content_type: str
    http_status: int = Field(ge=100, le=599)
    control: ResponseControl | None = None
    data: ResponseData


class PaginationField(RegistryModel):
    request: str


class Pagination(RegistryModel):
    type: Literal["page_number"]
    page: PaginationField
    page_size: PaginationField
    total_count: str


class ErrorDefinition(RegistryModel):
    http_status: int = Field(ge=100, le=599)
    source_code: str | None = None
    message: str


class Operation(IdentifiedModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    description: str | None = None
    idempotent: bool = False
    request: Request | None = None
    response: Response
    pagination: Pagination | None = None
    errors: list[ErrorDefinition] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("operation path must start with '/'")
        return value

    @model_validator(mode="after")
    def get_must_not_have_body(self) -> "Operation":
        if self.method in {"GET", "HEAD"} and self.request and self.request.body:
            raise ValueError(f"{self.method} operation cannot declare a request body")
        return self


class SourceDefinition(IdentifiedModel):
    provider: Provider
    type: Literal["api"]
    specification: Specification
    access: Access
    components: Components
    operations: list[Operation] = Field(min_length=1)


class SourceRegistry(RegistryModel):
    registry: RegistryMetadata
    source: SourceDefinition
